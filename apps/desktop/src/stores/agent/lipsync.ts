// src/stores/agent/lipsync.ts
import { clamp01 } from "./utils";

export type LipSyncController = {
    start: (audio: HTMLAudioElement) => void;
    stop: () => void;
};

let audioCtx: AudioContext | null = null;
let analyser: AnalyserNode | null = null;
let sourceNode: MediaElementAudioSourceNode | null = null;
let rafId: number | null = null;
let dataArray: Uint8Array | null = null;

export function createLipSync(opts: {
    isPlaying: () => boolean;
    setMouthOpen: (v: number) => void;
    debug?: (msg: string) => void;
}): LipSyncController {
    const debug = opts.debug ?? (() => { });

    const stop = () => {
        if (rafId) {
            cancelAnimationFrame(rafId);
            rafId = null;
        }
        try {
            sourceNode?.disconnect();
        } catch { }
        sourceNode = null;
        opts.setMouthOpen(0);
    };

    const start = (audio: HTMLAudioElement) => {
        if (!audioCtx) audioCtx = new AudioContext();
        audioCtx.resume().catch(() => { });

        if (!analyser) {
            analyser = audioCtx.createAnalyser();
            analyser.fftSize = 2048;
            dataArray = new Uint8Array(analyser.fftSize);
            // 只连一次 destination
            analyser.connect(audioCtx.destination);
        }

        if (sourceNode) {
            try {
                sourceNode.disconnect();
            } catch { }
        }

        try {
            sourceNode = audioCtx.createMediaElementSource(audio);
            sourceNode.connect(analyser);
        } catch (e) {
            debug(`WebAudio connect error: ${String(e)}`);
            return;
        }

        let smooth = 0;
        const noiseFloor = 0.02;
        const maxLevel = 0.18;

        const tick = () => {
            if (!analyser || !dataArray) return;
            if (!opts.isPlaying()) return;

            analyser.getByteTimeDomainData(dataArray as any);

            let sum = 0;
            for (let i = 0; i < dataArray.length; i++) {
                const v = (dataArray[i] - 128) / 128;
                sum += v * v;
            }
            const rms = Math.sqrt(sum / dataArray.length);
            const raw = clamp01((rms - noiseFloor) / (maxLevel - noiseFloor));

            smooth = smooth * 0.7 + raw * 0.3;
            opts.setMouthOpen(smooth);

            rafId = requestAnimationFrame(tick);
        };

        if (rafId) cancelAnimationFrame(rafId);
        rafId = requestAnimationFrame(tick);
    };

    return { start, stop };
}
