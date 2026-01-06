import { defineStore } from "pinia";
import { WebSocketService } from "../services/realtime/ws";

type ConnectionStatus = "disconnected" | "connected" | "closed";
type BackendState = "idle" | "thinking" | "speaking" | "listening";

type SessionInfo = {
    sessionId: string;
    serverInstanceId: string;
};

// Chat Message (UI)
export interface ChatMessage {
    id: string;
    role: "user" | "assistant";
    text: string;
    turnId: number;
    timestamp: number;
}

interface AgentState {
    connectionStatus: ConnectionStatus;
    backendState: BackendState;
    turnId: number;
    sessionInfo: SessionInfo | null;

    // UI
    messages: ChatMessage[];
    debugLog: string[];
    assistantText: string; // 你可能还会用它做“字幕”，所以保留

    // Audio receive/playback
    isPlaying: boolean;
    audioElement: HTMLAudioElement | null;
    audioChunks: Uint8Array[];
    audioMimeType: string;

    // 当前正在接收的音频流归属 turn（必须先 audio_begin 才会设置）
    audioTurnId: number | null;
    audioSeqExpected: number;

    // 当前播放的 blob url（用于 stopAudio/切换时 revoke）
    currentAudioUrl: string | null;

    // Lip sync
    mouthOpen: number; // 0..1
}

// ----- WebAudio closure (not in store) -----
let audioCtx: AudioContext | null = null;
let analyser: AnalyserNode | null = null;
let sourceNode: MediaElementAudioSourceNode | null = null;
let rafId: number | null = null;
let dataArray: Uint8Array | null = null;

// ----- utils -----
const now = () => Date.now();
const makeId = (prefix: string) => `${prefix}_${now()}_${Math.random().toString(16).slice(2)}`;

function clamp01(x: number) {
    return Math.max(0, Math.min(1, x));
}

function revokeIfBlob(url: string | null) {
    if (url && url.startsWith("blob:")) {
        try {
            URL.revokeObjectURL(url);
        } catch { }
    }
}

function base64ToU8(b64: string) {
    const bin = atob(b64);
    return Uint8Array.from(bin, (c) => c.charCodeAt(0));
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
        // ✅ 建议：全局统一的 UI 状态（给 StatusBadge / Avatar 共用）
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
            ws.onError(() => {
                this.addDebug("WS error");
            });

            ws.connect();
            this.connectionStatus = ws.isOpen() ? "connected" : "disconnected";
        },

        reconnect() {
            const ws = WebSocketService.getInstance();
            this.stopAudio("reconnect");

            ws.disconnect();
            this.connectionStatus = "disconnected";
            this.addDebug("WS reconnect...");

            ws.connect();
            this.connectionStatus = ws.isOpen() ? "connected" : "disconnected";
        },

        disconnect() {
            const ws = WebSocketService.getInstance();
            ws.disconnect();
            this.connectionStatus = "closed";
            this.stopAudio("disconnect");
            this.addDebug("WS disconnect");
        },

        sendUserText(text: string) {
            const ws = WebSocketService.getInstance();

            // 立刻静音，避免上一轮残留
            this.stopAudio("new_turn");
            this.assistantText = "";

            // UI：记一条 user message（turnId 暂时用当前 turnId，等后端返回会推进）
            this.messages.push({
                id: makeId("u"),
                role: "user",
                text,
                turnId: this.turnId,
                timestamp: now(),
            });

            // optimistic
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

        handleServerMessage(msg: Record<string, any>) {
            const t = msg?.type as string | undefined;
            const msgTurnId = typeof msg?.turn_id === "number" ? (msg.turn_id as number) : null;

            const isStaleTurn = (turn: number | null) => turn !== null && turn < this.turnId;
            const isCurrentTurn = (turn: number | null) => turn !== null && turn === this.turnId;

            // turn 前进：立刻作废旧音频 + 立刻静音（不要等 audio_end）
            const advanceTurn = (turn: number, reason: string) => {
                if (turn <= this.turnId) return;

                this.turnId = turn;

                // 作废旧音频 buffer 状态
                this.audioChunks = [];
                this.audioTurnId = null;
                this.audioSeqExpected = 0;

                // 防止旧音频继续响
                this.stopAudio(`turn_advance:${reason}`);

                this.addDebug(`turn -> ${turn} (${reason})`);
            };

            // ---- hello/reset：不走 stale 过滤 ----
            if (t === "hello") {
                this.sessionInfo = {
                    sessionId: msg.session_id,
                    serverInstanceId: msg.server_instance_id,
                };

                this.turnId = typeof msg.turn_id_reset === "number" ? msg.turn_id_reset : 0;
                this.backendState = "idle";

                // UI reset
                this.messages = [];
                this.debugLog = [];
                this.assistantText = "";

                // audio reset
                this.audioChunks = [];
                this.audioTurnId = null;
                this.audioSeqExpected = 0;
                this.stopAudio("hello_reset");

                this.addDebug(`hello: ${msg.msg}`);
                return;
            }

            // ---- stale drop ----
            // 带 turn_id 的旧业务消息全部丢弃（error 允许不带 turn_id）
            if (msgTurnId !== null && isStaleTurn(msgTurnId)) {
                // 旧 turn 的音频/文本都不要了
                return;
            }

            switch (t) {
                case "state_update": {
                    if (msgTurnId === null) return;
                    advanceTurn(msgTurnId, "state_update");
                    if (!isCurrentTurn(msgTurnId)) return;

                    const s = msg.state as BackendState;
                    this.backendState = s;
                    this.addDebug(`state_update -> ${s}`);
                    return;
                }

                case "assistant_reply": {
                    if (msgTurnId === null) return;
                    advanceTurn(msgTurnId, "assistant_reply");
                    if (!isCurrentTurn(msgTurnId)) return;

                    const text = msg.text || "";
                    this.assistantText = text;

                    // UI 对话记录
                    this.messages.push({
                        id: makeId(`a_${msgTurnId}`),
                        role: "assistant",
                        text,
                        turnId: msgTurnId,
                        timestamp: now(),
                    });

                    this.addDebug(`assistant_reply len=${text.length}`);
                    return;
                }

                // 未来如果做 streaming 文本
                case "assistant_delta": {
                    if (msgTurnId === null) return;
                    advanceTurn(msgTurnId, "assistant_delta");
                    if (!isCurrentTurn(msgTurnId)) return;

                    const delta = msg.delta || "";
                    this.assistantText = (this.assistantText || "") + delta;

                    // 同步写入 messages：如果上一条就是同 turn 的 assistant，就 append
                    const last = this.messages[this.messages.length - 1];
                    if (last && last.role === "assistant" && last.turnId === msgTurnId) {
                        last.text += delta;
                    } else {
                        this.messages.push({
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

                    this.audioTurnId = msgTurnId;
                    this.audioSeqExpected = 0;
                    this.audioMimeType = msg.mime || "audio/mpeg";
                    this.audioChunks = [];
                    this.addDebug(`audio_begin mime=${this.audioMimeType}`);
                    return;
                }

                case "audio_chunk": {
                    if (msgTurnId === null) return;
                    if (!isCurrentTurn(msgTurnId)) return;
                    if (this.audioTurnId !== msgTurnId) return; // 必须先 begin
                    if (!msg.data) return;

                    // seq gap 检查（可选）
                    if (typeof msg.seq === "number") {
                        const expected = this.audioSeqExpected ?? 0;
                        if (msg.seq !== expected) {
                            this.addDebug(`audio seq gap got=${msg.seq} exp=${expected}`);
                            this.audioSeqExpected = msg.seq + 1;
                        } else {
                            this.audioSeqExpected = expected + 1;
                        }
                    }

                    try {
                        this.audioChunks.push(base64ToU8(msg.data));
                    } catch {
                        this.addDebug("audio_chunk decode error");
                    }
                    return;
                }

                case "audio_end": {
                    if (msgTurnId === null) return;
                    if (!isCurrentTurn(msgTurnId)) return;
                    if (this.audioTurnId !== msgTurnId) return;

                    this.addDebug(`audio_end chunks=${this.audioChunks.length}`);
                    this.playBufferedAudio();

                    this.audioChunks = [];
                    this.audioTurnId = null;
                    return;
                }

                case "audio_cancel": {
                    // 未来你后端显式发 cancel 的话，可以用这个
                    if (msgTurnId !== null && isCurrentTurn(msgTurnId)) {
                        this.audioChunks = [];
                        this.audioTurnId = null;
                        this.audioSeqExpected = 0;
                        this.stopAudio("audio_cancel");
                    }
                    return;
                }

                case "error": {
                    // error 可能不带 turn_id
                    this.addDebug(`error: ${msg.msg}`);
                    return;
                }

                default: {
                    // 不要静默丢，方便你扩展消息类型
                    this.addDebug(`unhandled msg type=${String(t)}`);
                    return;
                }
            }
        },

        // ---------- Audio ----------
        playBufferedAudio() {
            if (this.audioChunks.length === 0) return;

            // merge chunks
            const totalLen = this.audioChunks.reduce((acc, c) => acc + c.length, 0);
            const merged = new Uint8Array(totalLen);
            let offset = 0;
            for (const c of this.audioChunks) {
                merged.set(c, offset);
                offset += c.length;
            }

            const blob = new Blob([merged], { type: this.audioMimeType });
            const url = URL.createObjectURL(blob);
            this.playAudio(url);
        },

        playAudio(url: string) {
            this.stopAudio("switch");
            this.currentAudioUrl = url;

            const audio = new Audio(url);
            this.audioElement = audio;

            audio.onplay = () => {
                this.isPlaying = true;
                this.startLipSync(audio);
                this.addDebug("audio play");
            };

            const cleanup = (reason: string) => {
                this.isPlaying = false;
                this.stopLipSync();

                // revoke 当前 url（只 revoke 自己这次的）
                if (this.currentAudioUrl === url) {
                    revokeIfBlob(this.currentAudioUrl);
                    this.currentAudioUrl = null;
                }

                this.addDebug(`audio stop (${reason})`);
            };

            audio.onended = () => cleanup("ended");
            audio.onerror = () => cleanup("error");

            audio.play().catch((e) => {
                this.addDebug(`audio.play failed: ${String(e)}`);
                cleanup("play_failed");
            });
        },

        stopAudio(reason: string) {
            if (this.audioElement) {
                try {
                    this.audioElement.pause();
                    this.audioElement.currentTime = 0;
                } catch { }
                this.audioElement = null;
            }

            revokeIfBlob(this.currentAudioUrl);
            this.currentAudioUrl = null;

            this.stopLipSync();
            this.isPlaying = false;

            // 清 buffer（避免旧 chunk 在下一次被误播放）
            this.audioChunks = [];
            this.audioTurnId = null;
            this.audioSeqExpected = 0;

            this.addDebug(`stopAudio: ${reason}`);
        },

        // ---------- Lip Sync ----------
        startLipSync(audio: HTMLAudioElement) {
            if (!audioCtx) audioCtx = new AudioContext();
            audioCtx.resume().catch(() => { });

            if (!analyser) {
                analyser = audioCtx.createAnalyser();
                analyser.fftSize = 2048;
                dataArray = new Uint8Array(analyser.fftSize);
                // 只需要连一次 destination
                analyser.connect(audioCtx.destination);
            }

            if (sourceNode) {
                try { sourceNode.disconnect(); } catch { }
            }

            try {
                sourceNode = audioCtx.createMediaElementSource(audio);
                sourceNode.connect(analyser);
            } catch (e) {
                this.addDebug(`WebAudio connect error: ${String(e)}`);
                return;
            }

            let smooth = 0;
            const noiseFloor = 0.02;
            const maxLevel = 0.18;

            const tick = () => {
                if (!analyser || !dataArray) return;
                if (!this.isPlaying) return;

                analyser.getByteTimeDomainData(dataArray as any);

                let sum = 0;
                for (let i = 0; i < dataArray.length; i++) {
                    const v = (dataArray[i] - 128) / 128;
                    sum += v * v;
                }
                const rms = Math.sqrt(sum / dataArray.length);
                const raw = clamp01((rms - noiseFloor) / (maxLevel - noiseFloor));

                smooth = smooth * 0.7 + raw * 0.3;
                this.mouthOpen = smooth;

                rafId = requestAnimationFrame(tick);
            };

            if (rafId) cancelAnimationFrame(rafId);
            rafId = requestAnimationFrame(tick);
        },

        stopLipSync() {
            if (rafId) {
                cancelAnimationFrame(rafId);
                rafId = null;
            }
            try { sourceNode?.disconnect(); } catch { }
            sourceNode = null;
            this.mouthOpen = 0;
        },
    },
});
