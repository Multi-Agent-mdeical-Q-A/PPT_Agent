// src/stores/agent/wsHandlers.ts
import type { BackendState, WsCtx, AudioMetric } from "./types";
import { base64ToU8, makeId, now } from "./utils";

const audioMetricMap = new Map<number, AudioMetric>();
const getMetric = (turn: number) => {
    let m = audioMetricMap.get(turn);
    if (!m) {
        m = { beginTs: performance.now(), chunkCount: 0, totalBytes: 0 };
        audioMetricMap.set(turn, m);
    }
    return m;
};

export function handleServerMessage(ctx: WsCtx, msg: Record<string, any>) {
    const t = msg?.type as string | undefined;
    const msgTurnId = typeof msg?.turn_id === "number" ? (msg.turn_id as number) : null;

    // ✅ audio_cancel must not be dropped
    if (t === "audio_cancel") {
        const cancelTurn = msgTurnId;

        // 1) 没有 turn_id：不做 destructive stop（避免误杀）
        if (typeof cancelTurn !== "number") {
            ctx.addDebug("audio_cancel without turn_id ignored");
            return;
        }

        // 2) cancel 的是旧 turn：忽略（不要影响当前 turn）
        if (cancelTurn < ctx.turnId) {
            ctx.addDebug(`audio_cancel stale turn=${cancelTurn} curr=${ctx.turnId} ignored`);
            return;
        }

        // 3) cancel 的是当前/未来 turn：才真正 stop
        if (cancelTurn > ctx.turnId) {
            // 如果 server cancel 的 turn 比当前大，说明 server 认为 turn 已推进
            ctx.turnId = cancelTurn;
            ctx.addDebug(`turn -> ${cancelTurn} (audio_cancel)`);
        }

        ctx.audioStreaming = false;
        ctx.stopAudio("audio_cancel");
        audioMetricMap.delete(cancelTurn);
        ctx.addDebug(`audio_cancel turn=${cancelTurn} applied`);
        return;
    }

    const isStaleTurn = (turn: number | null) => turn !== null && turn < ctx.turnId;
    const isCurrentTurn = (turn: number | null) => turn !== null && turn === ctx.turnId;

    const advanceTurn = (turn: number, reason: string) => {
        if (turn <= ctx.turnId) return;
        ctx.turnId = turn;
        ctx.stopAudio(`turn_advance:${reason}`);
        ctx.addDebug(`turn -> ${turn} (${reason})`);
    };

    // hello/reset
    if (t === "hello") {
        ctx.sessionInfo = {
            sessionId: msg.session_id,
            serverInstanceId: msg.server_instance_id,
        };

        ctx.turnId = typeof msg.turn_id_reset === "number" ? msg.turn_id_reset : 0;
        ctx.backendState = "idle";

        ctx.messages = [];
        ctx.debugLog = [];
        ctx.assistantText = "";

        ctx.audioIsPcm = false;
        ctx.stopAudio("hello_reset");
        ctx.addDebug(`hello: ${msg.msg}`);
        return;
    }

    if (msgTurnId !== null && isStaleTurn(msgTurnId)) {
        // drop stale
        return;
    }

    switch (t) {
        case "state_update": {
            if (msgTurnId === null) return;
            advanceTurn(msgTurnId, "state_update");
            if (!isCurrentTurn(msgTurnId)) return;

            ctx.backendState = msg.state as BackendState;
            ctx.addDebug(`state_update -> ${ctx.backendState}`);
            return;
        }

        case "assistant_reply":
        case "assistant_final": {
            if (msgTurnId === null) return;
            advanceTurn(msgTurnId, "assistant_final");
            if (!isCurrentTurn(msgTurnId)) return;

            const text = msg.text || "";
            ctx.assistantText = text;

            const last = ctx.messages[ctx.messages.length - 1];
            if (last && last.role === "assistant" && last.turnId === msgTurnId) {
                last.text = text;
            } else {
                ctx.messages.push({
                    id: makeId(`a_${msgTurnId}`),
                    role: "assistant",
                    text,
                    turnId: msgTurnId,
                    timestamp: now(),
                });
            }

            ctx.addDebug(`assistant_final len=${text.length}`);
            return;
        }

        case "assistant_delta": {
            if (msgTurnId === null) return;
            advanceTurn(msgTurnId, "assistant_delta");
            if (!isCurrentTurn(msgTurnId)) return;

            const delta = msg.delta || "";
            ctx.assistantText = (ctx.assistantText || "") + delta;

            const last = ctx.messages[ctx.messages.length - 1];
            if (last && last.role === "assistant" && last.turnId === msgTurnId) {
                last.text += delta;
            } else {
                ctx.messages.push({
                    id: makeId(`a_${msgTurnId}`),
                    role: "assistant",
                    text: delta,
                    turnId: msgTurnId,
                    timestamp: now(),
                });
            }
            return;
        }

        case "audio_begin": {
            if (msgTurnId === null) return;
            advanceTurn(msgTurnId, "audio_begin");
            if (!isCurrentTurn(msgTurnId)) return;

            // stop prev
            ctx.stopAudio("audio_begin");
            ctx.audioSeqExpected = 0;
            ctx.audioChunks = [];

            // metrics init
            const metric = getMetric(msgTurnId);
            metric.beginTs = performance.now();
            metric.firstChunkTs = undefined;
            metric.chunkCount = 0;
            metric.totalBytes = 0;
            metric.lastSeq = undefined;

            const format = msg.format as string | undefined;
            const sr = typeof msg.sample_rate === "number" ? msg.sample_rate : 24000;
            const ch = typeof msg.channels === "number" ? msg.channels : 1;

            if (format === "pcm_s16le") {
                ctx.audioIsPcm = true;
                ctx.audioStreaming = true;
                ctx.startPcmStream(sr, ch);
                ctx.addDebug(`audio_begin pcm sr=${sr} ch=${ch}`);
                return;
            }

            // compressed path
            ctx.audioIsPcm = false;
            ctx.audioMimeType = msg.mime || "audio/mpeg";
            const ok = ctx.startStream?.(ctx.audioMimeType) ?? false;
            ctx.audioStreaming = ok;
            ctx.addDebug(`audio_begin mime=${ctx.audioMimeType} streaming=${ok}`);
            return;
        }

        // Binary PCM frame (produced by ws.ts decoder)
        case "audio_chunk_bin": {
            if (msgTurnId === null) return;
            if (!isCurrentTurn(msgTurnId)) return;
            if (!ctx.audioIsPcm) return;

            const metric = getMetric(msgTurnId);

            const payload = msg.payload as Uint8Array | undefined;
            if (!payload || payload.length === 0) return;

            // seq tracking
            if (typeof msg.seq === "number") {
                const expected = ctx.audioSeqExpected ?? 0;
                if (msg.seq !== expected) {
                    ctx.addDebug(`audio seq gap got=${msg.seq} exp=${expected}`);
                    ctx.audioSeqExpected = msg.seq + 1;
                } else {
                    ctx.audioSeqExpected = expected + 1;
                }
                metric.lastSeq = msg.seq;
            }

            // metrics
            if (!metric.firstChunkTs) metric.firstChunkTs = performance.now();
            metric.chunkCount += 1;
            metric.totalBytes += payload.length;

            if (metric.chunkCount === 1 || metric.chunkCount % 10 === 0) {
                const firstDt = (metric.firstChunkTs - metric.beginTs).toFixed(0);
                ctx.addDebug(
                    `audio_chunk_bin #${metric.chunkCount} +${payload.length}B total=${metric.totalBytes}B first_dt=${firstDt}ms seq=${typeof msg.seq === "number" ? msg.seq : "-"}`
                );
            }

            ctx.appendPcmChunk(payload);
            return;
        }

        // Legacy base64 chunk (mp3/webm)
        case "audio_chunk": {
            if (msgTurnId === null) return;
            if (!isCurrentTurn(msgTurnId)) return;
            if (!msg.data) return;
            if (ctx.audioIsPcm) {
                // Ignore: in PCM mode we only accept binary chunks
                return;
            }

            const metric = getMetric(msgTurnId);
            if (typeof msg.seq === "number") {
                const expected = ctx.audioSeqExpected ?? 0;
                if (msg.seq !== expected) {
                    ctx.addDebug(`audio seq gap got=${msg.seq} exp=${expected}`);
                    ctx.audioSeqExpected = msg.seq + 1;
                } else {
                    ctx.audioSeqExpected = expected + 1;
                }
                metric.lastSeq = msg.seq;
            }

            try {
                const u8 = base64ToU8(msg.data);

                if (!metric.firstChunkTs) metric.firstChunkTs = performance.now();
                metric.chunkCount += 1;
                metric.totalBytes += u8.length;

                if (metric.chunkCount === 1 || metric.chunkCount % 10 === 0) {
                    const firstDt = (metric.firstChunkTs - metric.beginTs).toFixed(0);
                    ctx.addDebug(
                        `audio_chunk #${metric.chunkCount} +${u8.length}B total=${metric.totalBytes}B first_dt=${firstDt}ms seq=${typeof msg.seq === "number" ? msg.seq : "-"}`
                    );
                }

                if (ctx.audioStreaming && ctx.appendStreamChunk) {
                    ctx.appendStreamChunk(u8);
                } else {
                    ctx.audioChunks.push(u8);
                }
            } catch {
                ctx.addDebug("audio_chunk decode error");
            }
            return;
        }

        case "audio_end": {
            if (msgTurnId === null) return;
            if (!isCurrentTurn(msgTurnId)) return;

            const metric = audioMetricMap.get(msgTurnId);
            const summary = metric
                ? `chunks=${metric.chunkCount} bytes=${metric.totalBytes} lastSeq=${metric.lastSeq ?? "-"}`
                : `chunks=? bytes=?`;

            ctx.addDebug(`audio_end pcm=${ctx.audioIsPcm} streaming=${ctx.audioStreaming} | ${summary}`);

            if (ctx.audioIsPcm) {
                // ✅ IMPORTANT: never call playBufferedAudio for PCM!
                ctx.endPcmStream();
                ctx.audioStreaming = false;
                ctx.audioIsPcm = false;
                audioMetricMap.delete(msgTurnId);
                return;
            }

            if (ctx.audioStreaming && ctx.endStream) {
                ctx.endStream();
            } else {
                ctx.playBufferedAudio();
                ctx.audioChunks = [];
            }

            ctx.audioStreaming = false;
            audioMetricMap.delete(msgTurnId);
            return;
        }

        case "error": {
            ctx.addDebug(`error: ${msg.msg}`);
            return;
        }

        default: {
            // ignore noisy internal ws messages
            if (t !== "ws_binary") ctx.addDebug(`unhandled msg type=${String(t)}`);
            return;
        }
    }
}
