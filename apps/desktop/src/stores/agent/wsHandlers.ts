// src/stores/agent/wsHandlers.ts
import type { BackendState, WsCtx } from "./types";
import { base64ToU8, makeId, now } from "./utils";


export function handleServerMessage(ctx: WsCtx, msg: Record<string, any>) {
    const t = msg?.type as string | undefined;
    const msgTurnId = typeof msg?.turn_id === "number" ? (msg.turn_id as number) : null;

    const isStaleTurn = (turn: number | null) => turn !== null && turn < ctx.turnId;
    const isCurrentTurn = (turn: number | null) => turn !== null && turn === ctx.turnId;

    const advanceTurn = (turn: number, reason: string) => {
        if (turn <= ctx.turnId) return;

        ctx.turnId = turn;

        // 作废旧音频 buffer 状态
        ctx.audioChunks = [];
        ctx.audioTurnId = null;
        ctx.audioSeqExpected = 0;

        // 防止旧音频继续响
        ctx.stopAudio(`turn_advance:${reason}`);

        ctx.addDebug(`turn -> ${turn} (${reason})`);
    };

    // hello/reset：不走 stale 过滤
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

        ctx.audioChunks = [];
        ctx.audioTurnId = null;
        ctx.audioSeqExpected = 0;
        ctx.stopAudio("hello_reset");

        ctx.addDebug(`hello: ${msg.msg}`);
        return;
    }

    // stale drop
    if (msgTurnId !== null && isStaleTurn(msgTurnId)) return;

    switch (t) {
        case "state_update": {
            if (msgTurnId === null) return;
            advanceTurn(msgTurnId, "state_update");
            if (!isCurrentTurn(msgTurnId)) return;

            ctx.backendState = msg.state as BackendState;
            ctx.addDebug(`state_update -> ${ctx.backendState}`);
            return;
        }

        case "assistant_reply": {
            if (msgTurnId === null) return;
            advanceTurn(msgTurnId, "assistant_reply");
            if (!isCurrentTurn(msgTurnId)) return;

            const text = msg.text || "";
            ctx.assistantText = text;

            ctx.messages.push({
                id: makeId(`a_${msgTurnId}`),
                role: "assistant",
                text,
                turnId: msgTurnId,
                timestamp: now(),
            });

            ctx.addDebug(`assistant_reply len=${text.length}`);
            return;
        }
        // 暂时不用
        // case "assistant_delta": {
        //     if (msgTurnId === null) return;
        //     advanceTurn(msgTurnId, "assistant_delta");
        //     if (!isCurrentTurn(msgTurnId)) return;

        //     const delta = msg.delta || "";
        //     ctx.assistantText = (ctx.assistantText || "") + delta;

        //     const last = ctx.messages[ctx.messages.length - 1];
        //     if (last && last.role === "assistant" && last.turnId === msgTurnId) {
        //         last.text += delta;
        //     } else {
        //         ctx.messages.push({
        //             id: makeId(`a_${msgTurnId}`),
        //             role: "assistant",
        //             text: delta,
        //             turnId: msgTurnId,
        //             timestamp: now(),
        //         });
        //     }
        //     return;
        // }

        case "audio_begin": {
            if (msgTurnId === null) return;
            advanceTurn(msgTurnId, "audio_begin");
            if (!isCurrentTurn(msgTurnId)) return;

            ctx.audioTurnId = msgTurnId;
            ctx.audioSeqExpected = 0;
            ctx.audioMimeType = msg.mime || "audio/mpeg";
            ctx.audioChunks = [];
            ctx.addDebug(`audio_begin mime=${ctx.audioMimeType}`);
            return;
        }

        case "audio_chunk": {
            if (msgTurnId === null) return;
            if (!isCurrentTurn(msgTurnId)) return;
            if (ctx.audioTurnId !== msgTurnId) return;
            if (!msg.data) return;

            if (typeof msg.seq === "number") {
                const expected = ctx.audioSeqExpected ?? 0;
                if (msg.seq !== expected) {
                    ctx.addDebug(`audio seq gap got=${msg.seq} exp=${expected}`);
                    ctx.audioSeqExpected = msg.seq + 1;
                } else {
                    ctx.audioSeqExpected = expected + 1;
                }
            }

            try {
                ctx.audioChunks.push(base64ToU8(msg.data));
            } catch {
                ctx.addDebug("audio_chunk decode error");
            }
            return;
        }

        case "audio_end": {
            if (msgTurnId === null) return;
            if (!isCurrentTurn(msgTurnId)) return;
            if (ctx.audioTurnId !== msgTurnId) return;

            ctx.addDebug(`audio_end chunks=${ctx.audioChunks.length}`);
            ctx.playBufferedAudio();

            ctx.audioChunks = [];
            ctx.audioTurnId = null;
            return;
        }

        case "audio_cancel": {
            if (msgTurnId !== null && isCurrentTurn(msgTurnId)) {
                ctx.audioChunks = [];
                ctx.audioTurnId = null;
                ctx.audioSeqExpected = 0;
                ctx.stopAudio("audio_cancel");
            }
            return;
        }

        case "error": {
            ctx.addDebug(`error: ${msg.msg}`);
            return;
        }

        default: {
            ctx.addDebug(`unhandled msg type=${String(t)}`);
            return;
        }
    }
}
