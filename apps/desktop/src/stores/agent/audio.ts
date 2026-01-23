// src/stores/agent/audio.ts
import { revokeIfBlob } from "./utils";
import type { LipSyncController } from "./lipsync";
import type { AudioCtx } from "./types";

// =====================================================
// 1) MSE (compressed audio: mp3/webm) streaming
// =====================================================
let mediaSource: MediaSource | null = null;
let sourceBuffer: SourceBuffer | null = null;
let mseQueue: Uint8Array[] = [];
let isMseStreamActive = false;

export function startStream(ctx: AudioCtx, lip: LipSyncController, mime: string) {
    if (!window.MediaSource || !MediaSource.isTypeSupported(mime)) {
        ctx.addDebug(`MSE not supported for ${mime}, fallback to buffer`);
        return false;
    }

    ctx.addDebug(`startStream: ${mime}`);
    mediaSource = new MediaSource();
    mseQueue = [];
    isMseStreamActive = true;

    const url = URL.createObjectURL(mediaSource);
    ctx.setCurrentAudioUrl(url);

    const audio = new Audio(url);
    ctx.setAudioElement(audio);

    audio.onplay = () => {
        ctx.setIsPlaying(true);
        lip.startElement(audio);
        ctx.addDebug("stream play");
    };
    audio.onended = () => {
        resetMseState();
        ctx.setIsPlaying(false);
        lip.stop();
        ctx.addDebug("stream ended");
    };
    audio.onerror = (e) => {
        const errType = e instanceof Event ? e.type : String(e);
        ctx.addDebug(`stream error: ${errType}`);
        stopAudio(ctx, lip, "stream_error");
    };

    mediaSource.onsourceopen = () => {
        if (!mediaSource || mediaSource.readyState !== "open") return;
        try {
            sourceBuffer = mediaSource.addSourceBuffer(mime);
            sourceBuffer.mode = "sequence";
            sourceBuffer.onupdateend = () => processMseQueue(ctx);
            ctx.addDebug("MSE sourceopen success");
        } catch (e) {
            ctx.addDebug(`MSE addBuffer error: ${e}`);
        }
    };

    audio.play().catch((e) => ctx.addDebug(`stream play fail: ${e}`));
    return true;
}

export function appendStreamChunk(ctx: AudioCtx, chunk: Uint8Array) {
    if (!isMseStreamActive) return;
    mseQueue.push(chunk);
    processMseQueue(ctx);
}

export function endStream(ctx: AudioCtx) {
    if (!mediaSource || mediaSource.readyState !== "open") return;

    const checkEnd = () => {
        if (!sourceBuffer) return;
        if (sourceBuffer.updating || mseQueue.length > 0) {
            setTimeout(checkEnd, 50);
            return;
        }
        try {
            if (mediaSource && mediaSource.readyState === "open") {
                mediaSource.endOfStream();
                ctx.addDebug("MSE endOfStream");
            }
        } catch (e) {
            ctx.addDebug(`endOfStream error: ${e}`);
        }
    };

    try {
        checkEnd();
    } catch (e) {
        ctx.addDebug(`endStream error: ${e}`);
    }
}

export function cancelStream(ctx: AudioCtx) {
    if (!isMseStreamActive) return;
    ctx.addDebug("cancelStream");
    resetMseState();
}

function processMseQueue(ctx: AudioCtx) {
    if (!sourceBuffer || sourceBuffer.updating || mseQueue.length === 0) return;
    const chunk = mseQueue.shift();
    if (!chunk) return;

    try {
        sourceBuffer.appendBuffer(chunk as any);
        ctx.addDebug(`MSE append ${chunk.length}B`);
    } catch (e) {
        ctx.addDebug(`MSE append error: ${e}`);
    }
}

function resetMseState() {
    isMseStreamActive = false;
    mseQueue = [];
    if (sourceBuffer) {
        try {
            sourceBuffer.abort();
        } catch {}
        sourceBuffer = null;
    }
    mediaSource = null;
}

// =====================================================
// 2) PCM (pcm_s16le) WebAudio streaming
// =====================================================
let pcmCtx: AudioContext | null = null;
let pcmGain: GainNode | null = null;
let pcmQueue: Uint8Array[] = [];
let pcmNextTime = 0;
let pcmStarted = false;
let pcmEnded = false;
let pcmChannels = 1;
let pcmSampleRate = 24000;
let pcmSources: AudioBufferSourceNode[] = [];
let pcmEndTimer: number | null = null;

export function startPcmStream(ctx: AudioCtx, lip: LipSyncController, sampleRate: number, channels: number) {
    // tear down previous pcm pipeline
    resetPcmState();

    pcmSampleRate = sampleRate;
    pcmChannels = channels;
    pcmQueue = [];
    pcmEnded = false;
    pcmStarted = false;

    // NOTE: some environments ignore the sampleRate option; still works.
    pcmCtx = new AudioContext({ sampleRate });
    pcmGain = pcmCtx.createGain();
    pcmGain.connect(pcmCtx.destination);

    // Mark playing (UI / lipsync)
    ctx.setIsPlaying(true);

    // Use gain node as tap point for lipsync
    lip.startNode(pcmCtx, pcmGain);

    // Small initial buffer to avoid underrun
    pcmNextTime = pcmCtx.currentTime + 0.05;

    ctx.addDebug(`startPcmStream sr=${sampleRate} ch=${channels}`);
    // resume (in case of auto-suspend)
    pcmCtx.resume().catch(() => {});
    return true;
}

export function appendPcmChunk(ctx: AudioCtx, chunk: Uint8Array) {
    if (!pcmCtx || !pcmGain) return;
    pcmQueue.push(chunk);
    processPcmQueue(ctx);
}

export function endPcmStream(ctx: AudioCtx) {
    pcmEnded = true;
    // schedule a finish check
    schedulePcmEndCheck(ctx);
}

export function cancelPcmStream(ctx: AudioCtx, lip: LipSyncController) {
    ctx.addDebug("cancelPcmStream");
    resetPcmState();
    lip.stop();
    ctx.setIsPlaying(false);
}

function processPcmQueue(ctx: AudioCtx) {
    if (!pcmCtx || !pcmGain) return;

    while (pcmQueue.length > 0) {
        const u8 = pcmQueue.shift()!;

        // PCM16LE: bytes -> samples
        const bytesPerSample = 2;
        const frameCount = Math.floor(u8.byteLength / bytesPerSample / pcmChannels);
        if (frameCount <= 0) continue;

        const buffer = pcmCtx.createBuffer(pcmChannels, frameCount, pcmSampleRate);
        const view = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);

        // Fill per-channel
        for (let ch = 0; ch < pcmChannels; ch++) {
            const channel = buffer.getChannelData(ch);
            let idx = 0;
            // interleaved s16le
            for (let i = 0; i < frameCount; i++) {
                const sampleIndex = (i * pcmChannels + ch) * 2;
                const s = view.getInt16(sampleIndex, true);
                channel[idx++] = s / 32768;
            }
        }

        const src = pcmCtx.createBufferSource();
        src.buffer = buffer;
        src.connect(pcmGain);

        const startAt = Math.max(pcmNextTime, pcmCtx.currentTime + 0.005);
        try {
            src.start(startAt);
        } catch {
            // if start fails, stop everything
            resetPcmState();
            ctx.setIsPlaying(false);
            return;
        }

        pcmSources.push(src);
        pcmNextTime = startAt + buffer.duration;

        // cleanup finished sources
        src.onended = () => {
            pcmSources = pcmSources.filter((s) => s !== src);
            if (pcmEnded) schedulePcmEndCheck(ctx);
        };

        if (!pcmStarted) {
            pcmStarted = true;
        }
    }

    if (pcmEnded) schedulePcmEndCheck(ctx);
}

function schedulePcmEndCheck(ctx: AudioCtx) {
    if (pcmEndTimer) window.clearTimeout(pcmEndTimer);

    // If nothing left queued/scheduled, stop now
    if (!pcmCtx) {
        ctx.setIsPlaying(false);
        return;
    }

    const remaining = pcmNextTime - pcmCtx.currentTime;
    if ((pcmQueue.length === 0) && (pcmSources.length === 0 || remaining <= 0.02)) {
        // end
        resetPcmState();
        ctx.setIsPlaying(false);
        ctx.addDebug("pcm ended");
        return;
    }

    // check again around the expected end time
    const waitMs = Math.max(20, Math.min(500, remaining * 1000));
    pcmEndTimer = window.setTimeout(() => schedulePcmEndCheck(ctx), waitMs);
}

function resetPcmState() {
    pcmQueue = [];
    pcmEnded = false;
    pcmStarted = false;

    if (pcmEndTimer) {
        window.clearTimeout(pcmEndTimer);
        pcmEndTimer = null;
    }

    // stop scheduled sources
    for (const s of pcmSources) {
        try {
            s.stop();
        } catch {}
        try {
            s.disconnect();
        } catch {}
    }
    pcmSources = [];

    if (pcmGain) {
        try {
            pcmGain.disconnect();
        } catch {}
        pcmGain = null;
    }

    if (pcmCtx) {
        // closing releases resources; ignore errors
        try {
            pcmCtx.close();
        } catch {}
        pcmCtx = null;
    }
    pcmNextTime = 0;
}

// =====================================================
// 3) Buffered audio playback (non-streaming compressed)
// =====================================================
export function playBufferedAudio(ctx: AudioCtx, lip: LipSyncController) {
    // If streaming is active, don't switch to buffered (stream will finish itself)
    if (isMseStreamActive) return;

    if (ctx.audioChunks.length === 0) return;

    // Guard: PCM should never reach here
    if (ctx.audioMimeType === "audio/L16" || ctx.audioMimeType.includes("L16") || ctx.audioMimeType.includes("pcm")) {
        ctx.addDebug(`playBufferedAudio skipped for mime=${ctx.audioMimeType}`);
        ctx.resetAudioBuffer();
        return;
    }

    const totalLen = ctx.audioChunks.reduce((acc, c) => acc + c.length, 0);
    const merged = new Uint8Array(totalLen);
    let offset = 0;
    for (const c of ctx.audioChunks) {
        merged.set(c, offset);
        offset += c.length;
    }

    const blob = new Blob([merged], { type: ctx.audioMimeType });
    const url = URL.createObjectURL(blob);
    playAudio(ctx, lip, url);
}

export function playAudio(ctx: AudioCtx, lip: LipSyncController, url: string) {
    stopAudio(ctx, lip, "switch");
    ctx.setCurrentAudioUrl(url);

    const audio = new Audio(url);
    ctx.setAudioElement(audio);

    audio.onplay = () => {
        ctx.setIsPlaying(true);
        lip.startElement(audio);
        ctx.addDebug("audio play");
    };

    const cleanup = (reason: string) => {
        ctx.setIsPlaying(false);
        lip.stop();

        if (ctx.currentAudioUrl === url) {
            revokeIfBlob(ctx.currentAudioUrl);
            ctx.setCurrentAudioUrl(null);
        }
        ctx.addDebug(`audio stop (${reason})`);
    };

    audio.onended = () => cleanup("ended");
    audio.onerror = () => cleanup("error");

    audio.play().catch((e) => {
        ctx.addDebug(`audio.play failed: ${String(e)}`);
        cleanup("play_failed");
    });
}

export function stopAudio(ctx: AudioCtx, lip: LipSyncController, reason: string) {
    // Stop both pipelines
    resetMseState();
    resetPcmState();

    if (ctx.audioElement) {
        try {
            ctx.audioElement.pause();
            ctx.audioElement.currentTime = 0;
        } catch {}
        ctx.setAudioElement(null);
    }

    revokeIfBlob(ctx.currentAudioUrl);
    ctx.setCurrentAudioUrl(null);

    lip.stop();
    ctx.setIsPlaying(false);

    ctx.resetAudioBuffer();
    ctx.addDebug(`stopAudio: ${reason}`);
}
