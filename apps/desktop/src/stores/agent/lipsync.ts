// src/stores/agent/lipsync.ts
import { clamp01 } from "./utils";

export type LipSyncController = {
    /** HTMLAudioElement path (MSE/blob). */
    startElement: (audio: HTMLAudioElement) => void;
    /** WebAudio path (PCM): tap an existing AudioNode (e.g., GainNode) for analyser. */
    startNode: (ctx: AudioContext, node: AudioNode) => void;
    /** Back-compat alias of startElement. */
    start?: (audio: HTMLAudioElement) => void;
    stop: () => void;
};

type Mode = "none" | "element" | "node";

export function createLipSync(opts: {
    isPlaying: () => boolean;
    setMouthOpen: (v: number) => void;
    debug?: (msg: string) => void;
}): LipSyncController {
    const debug = opts.debug ?? (() => { });

    // --- modes / contexts ---
    let mode: Mode = "none";

    // element mode uses its own AudioContext (because createMediaElementSource is bound to a context)
    let elementCtx: AudioContext | null = null;
    let elementSource: MediaElementAudioSourceNode | null = null;

    // active context for current analyser (either elementCtx or PCM ctx)
    let activeCtx: AudioContext | null = null;

    // analyser (must belong to activeCtx)
    let analyser: AnalyserNode | null = null;
    // NOTE: explicitly use ArrayBuffer to avoid TS Uint8Array<ArrayBufferLike> mismatch
    let dataArray: Uint8Array<ArrayBuffer> | null = null;

    // pcm tapped node (belongs to activeCtx)
    let tappedNode: AudioNode | null = null;

    let rafId: number | null = null;

    const ensureCtxForElement = () => {
        if (!elementCtx) elementCtx = new AudioContext();
        elementCtx.resume().catch(() => { });
        return elementCtx;
    };

    const stopTick = () => {
        if (rafId !== null) {
            cancelAnimationFrame(rafId);
            rafId = null;
        }
    };

    const disconnectInputs = () => {
        // element input
        if (elementSource) {
            try {
                elementSource.disconnect();
            } catch { }
            elementSource = null;
        }

        // node tap input
        if (tappedNode && analyser) {
            try {
                tappedNode.disconnect(analyser);
            } catch { }
        }
        tappedNode = null;

        // element mode: we connected analyser->destination, so detach it when leaving element mode
        if (mode === "element" && analyser && activeCtx) {
            try {
                analyser.disconnect(activeCtx.destination);
            } catch { }
        }

        mode = "none";
    };

    const ensureAnalyserFor = (ctx: AudioContext) => {
        // if context changed, the old analyser is invalid for new nodes: rebuild
        if (activeCtx !== ctx) {
            disconnectInputs();
            analyser = null;
            dataArray = null;
            activeCtx = ctx;
        }

        if (!analyser) {
            analyser = ctx.createAnalyser();
            analyser.fftSize = 1024;
            analyser.smoothingTimeConstant = 0.8;

            const buf = new ArrayBuffer(analyser.fftSize);
            dataArray = new Uint8Array(buf) as Uint8Array<ArrayBuffer>;
        }
    };

    const startTick = () => {
        stopTick();

        let smooth = 0;
        const noiseFloor = 0.02;
        const maxLevel = 0.18;

        const tick = () => {
            if (!analyser || !dataArray) return;

            // 关键：不要在 isPlaying=false 时直接 return，否则下一次播放不会自动恢复
            if (!opts.isPlaying()) {
                opts.setMouthOpen(0);
                rafId = requestAnimationFrame(tick);
                return;
            }

            // analyser.getByteTimeDomainData expects Uint8Array; TS 泛型有时会挑剔，直接 cast 最稳
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

        rafId = requestAnimationFrame(tick);
    };

    const startElement = (audio: HTMLAudioElement) => {
        const ctx = ensureCtxForElement();
        ensureAnalyserFor(ctx);
        if (!analyser) return;

        disconnectInputs();
        mode = "element";

        try {
            // element: source -> analyser -> destination
            elementSource = ctx.createMediaElementSource(audio);
            elementSource.connect(analyser);
            analyser.connect(ctx.destination);
        } catch (e) {
            debug(`WebAudio element connect error: ${String(e)}`);
            disconnectInputs();
            return;
        }

        startTick();
    };

    const startNode = (ctx: AudioContext, node: AudioNode) => {
        // PCM/WebAudio mode: analyser MUST be created in the same ctx as node
        ensureAnalyserFor(ctx);
        if (!analyser) return;

        disconnectInputs();
        mode = "node";

        try {
            // tap only: node -> analyser (do NOT connect analyser to destination)
            node.connect(analyser);
            tappedNode = node;
        } catch (e) {
            debug(`WebAudio tap connect error: ${String(e)}`);
            disconnectInputs();
            return;
        }

        startTick();
    };

    const stop = () => {
        stopTick();
        disconnectInputs();
        opts.setMouthOpen(0);
    };

    const start = startElement;
    return { startElement, startNode, start, stop };
}
