// src/stores/agent/index.ts
import { defineStore } from "pinia";
import { WebSocketService } from "../../services/realtime/ws";

import type { AgentState, WsCtx, AudioCtx } from "./types";
import { makeId, now } from "./utils";
import { createLipSync, type LipSyncController } from "./lipsync";
import {
    playBufferedAudio as _playBufferedAudio,
    playAudio as _playAudio,
    stopAudio as _stopAudio,
} from "./audio";
import { handleServerMessage as _handleServerMessage } from "./wsHandlers";

// ✅ store 单例：模块级缓存 lip controller 就够了
let _lipController: LipSyncController | null = null;

function getLip(store: any): LipSyncController {
    if (!_lipController) {
        _lipController = createLipSync({
            isPlaying: () => store.isPlaying,
            setMouthOpen: (v) => (store.mouthOpen = v),
            debug: (m) => store.addDebug(m),
        });
    }
    return _lipController;
}

export const useAgentStore = defineStore("agent", {
    state: (): AgentState => ({
        connectionStatus: "disconnected",
        backendState: "idle",
        turnId: 0,
        sessionInfo: null,

        messages: [],
        debugLog: [],
        assistantText: "",

        isPlaying: false,
        audioElement: null,
        audioChunks: [],
        audioMimeType: "audio/wav",

        audioTurnId: null,
        audioSeqExpected: 0,

        currentAudioUrl: null,

        mouthOpen: 0,
    }),

    getters: {
        // ✅ 统一 UI 状态（Avatar / StatusBadge 共用）
        uiState(state): "idle" | "thinking" | "speaking" {
            if (state.isPlaying) return "speaking";
            if (state.backendState === "thinking") return "thinking";
            return "idle";
        },
    },

    actions: {
        addDebug(msg: string) {
            this.debugLog.unshift(`${new Date().toLocaleTimeString()} ${msg}`);
        },

        connect() {
            console.trace("[AgentStore] connect called");
            const ws = WebSocketService.getInstance();

            ws.onMessage((msg) => this.handleServerMessage(msg));
            ws.onOpen(() => {
                this.connectionStatus = "connected";
                this.addDebug("WS open");
            });
            ws.onClose(() => {
                this.connectionStatus = "closed";
                this.addDebug("WS close");
            });
            ws.onError(() => this.addDebug("WS error"));

            ws.connect();
            if (ws.isOpen()) this.connectionStatus = "connected";
            else if (ws.isConnecting()) this.connectionStatus = "connecting";
            else this.connectionStatus = "disconnected";
        },

        reconnect() {
            const ws = WebSocketService.getInstance();

            // ✅ 正在连接就不要重连（否则永远连不上）
            if (ws.isConnecting()) {
                this.addDebug("WS is connecting... skip reconnect");
                this.connectionStatus = "connecting";
                return;
            }

            this.stopAudio("reconnect");
            this.addDebug("WS reconnect...");

            ws.disconnect();
            ws.connect();

            if (ws.isOpen()) this.connectionStatus = "connected";
            else if (ws.isConnecting()) this.connectionStatus = "connecting";
            else this.connectionStatus = "disconnected";
        },

        disconnect() {
            console.trace("[AgentStore] connect called");
            const ws = WebSocketService.getInstance();
            ws.disconnect();
            this.connectionStatus = "closed";
            this.stopAudio("disconnect");
            this.addDebug("WS disconnect");
        },

        sendUserText(text: string) {
            const ws = WebSocketService.getInstance();

            this.stopAudio("new_turn");
            this.assistantText = "";
            // ✅ 乐观 turn +1：和后端保持一致
            const nextTurnId = this.turnId + 1;
            this.turnId = nextTurnId;
            this.messages.push({
                id: makeId("u"),
                role: "user",
                text,
                turnId: this.turnId,
                timestamp: now(),
            });

            this.backendState = "thinking";
            this.addDebug(`send user_text (${text.slice(0, 30)})`);
            ws.send({ type: "user_text", text });
        },

        triggerInterrupt() {
            const ws = WebSocketService.getInstance();
            this.stopAudio("interrupt");
            this.backendState = "idle";
            this.addDebug("send interrupt");
            ws.send({ type: "interrupt" });
        },

        // ✅ 用 WsCtx 适配对象（比 this as any 更稳）
        handleServerMessage(msg: Record<string, any>) {
            const thisStore = this;

            const wsCtx: WsCtx = {
                get turnId() { return thisStore.turnId; },
                set turnId(v: number) { thisStore.turnId = v; },

                get backendState() { return thisStore.backendState; },
                set backendState(v) { thisStore.backendState = v; },

                get sessionInfo() { return thisStore.sessionInfo; },
                set sessionInfo(v) { thisStore.sessionInfo = v; },

                get messages() { return thisStore.messages; },
                set messages(v) { thisStore.messages = v; },

                get debugLog() { return thisStore.debugLog; },
                set debugLog(v) { thisStore.debugLog = v; },

                get assistantText() { return thisStore.assistantText; },
                set assistantText(v: string) { thisStore.assistantText = v; },

                get audioChunks() { return thisStore.audioChunks; },
                set audioChunks(v: Uint8Array[]) { thisStore.audioChunks = v; },

                get audioMimeType() { return thisStore.audioMimeType; },
                set audioMimeType(v: string) { thisStore.audioMimeType = v; },

                get audioTurnId() { return thisStore.audioTurnId; },
                set audioTurnId(v: number | null) { thisStore.audioTurnId = v; },

                get audioSeqExpected() { return thisStore.audioSeqExpected; },
                set audioSeqExpected(v: number) { thisStore.audioSeqExpected = v; },

                addDebug: (m) => thisStore.addDebug(m),
                stopAudio: (r) => thisStore.stopAudio(r),
                playBufferedAudio: () => thisStore.playBufferedAudio(),
            };

            _handleServerMessage(wsCtx, msg);
        }
        ,

        // ---- audio wrappers（委托到模块）----
        playBufferedAudio() {
            _playBufferedAudio(this._audioCtx(), getLip(this));
        },

        playAudio(url: string) {
            _playAudio(this._audioCtx(), getLip(this), url);
        },

        stopAudio(reason: string) {
            _stopAudio(this._audioCtx(), getLip(this), reason);
        },

        // ✅ 关键修复：AudioCtx 用 getter/setter，避免“快照 bug”
        _audioCtx(): AudioCtx {
            const store = this;
            return {
                get isPlaying() {
                    return store.isPlaying;
                },
                get audioElement() {
                    return store.audioElement;
                },
                get audioChunks() {
                    return store.audioChunks;
                },
                get audioMimeType() {
                    return store.audioMimeType;
                },
                get currentAudioUrl() {
                    return store.currentAudioUrl;
                },

                get audioTurnId() {
                    return store.audioTurnId;
                },
                get audioSeqExpected() {
                    return store.audioSeqExpected;
                },

                addDebug: (m: string) => store.addDebug(m),
                setIsPlaying: (v: boolean) => (store.isPlaying = v),
                setAudioElement: (el: HTMLAudioElement | null) => (store.audioElement = el),
                setCurrentAudioUrl: (u: string | null) => (store.currentAudioUrl = u),

                resetAudioBuffer: () => {
                    store.audioChunks = [];
                    store.audioTurnId = null;
                    store.audioSeqExpected = 0;
                },
            };
        },
    },
});
