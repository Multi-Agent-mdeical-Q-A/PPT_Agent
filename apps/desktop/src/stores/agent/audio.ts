// src/stores/agent/audio.ts
import { revokeIfBlob } from "./utils";
import type { LipSyncController } from "./lipsync";
import type { AudioCtx } from "./types";


export function playBufferedAudio(ctx: AudioCtx, lip: LipSyncController) {
    if (ctx.audioChunks.length === 0) return;

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
        lip.start(audio);
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
    if (ctx.audioElement) {
        try {
            ctx.audioElement.pause();
            ctx.audioElement.currentTime = 0;
        } catch { }
        ctx.setAudioElement(null);
    }

    revokeIfBlob(ctx.currentAudioUrl);
    ctx.setCurrentAudioUrl(null);

    lip.stop();
    ctx.setIsPlaying(false);

    ctx.resetAudioBuffer();
    ctx.addDebug(`stopAudio: ${reason}`);
}
