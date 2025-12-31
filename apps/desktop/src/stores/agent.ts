import { defineStore } from "pinia";
import { WebSocketService } from "../services/realtime/ws";

type ConnectionStatus = "disconnected" | "connected" | "closed";
type BackendState = "idle" | "thinking" | "speaking" | "listening";
type SessionInfo = {
    sessionId: string;
    serverInstanceId: string;
};

interface AgentState {
    connectionStatus: ConnectionStatus;
    backendState: BackendState;
    turnId: number;
    // Track which turn the incoming audio stream belongs to
    latestAudioTurnId: number;
    sessionInfo: SessionInfo | null;
    chatLog: string[];
    assistantText: string;
    // Audio state
    isPlaying: boolean;
    audioElement: HTMLAudioElement | null;
}

export const useAgentStore = defineStore("agent", {
    state: (): AgentState => ({
        connectionStatus: "disconnected",
        backendState: "idle",
        turnId: 0,
        latestAudioTurnId: 0,
        sessionInfo: null,
        chatLog: [],
        assistantText: "",
        isPlaying: false,
        audioElement: null,
    }),

    actions: {
        connect() {
            const ws = WebSocketService.getInstance();

            // Wire up handlers with proper binding
            ws.onMessage((msg) => this.handleServerMessage(msg));
            ws.onOpen(() => { this.connectionStatus = "connected"; });
            ws.onClose(() => { this.connectionStatus = "closed"; });
            ws.onError(() => { this.addLog("WS Error"); });

            ws.connect();
            this.connectionStatus = ws.isOpen() ? "connected" : "disconnected";
        },

        reconnect() {
            const ws = WebSocketService.getInstance();
            this.stopAudio("reconnect");

            ws.disconnect();                 // 强制断开
            this.connectionStatus = "disconnected";
            ws.connect();                    // 再连接

            // 可选：立即按当前状态更新一次，避免早退导致假状态
            this.connectionStatus = ws.isOpen() ? "connected" : "disconnected";
        },

        disconnect() {
            const ws = WebSocketService.getInstance();
            ws.disconnect();
            this.connectionStatus = "closed";
            this.stopAudio("disconnect");
        },

        sendUserText(text: string) {
            const ws = WebSocketService.getInstance();
            // Optimistic update
            this.backendState = "thinking";
            this.addLog(`User: ${text}`);

            // We do NOT increment turnId locally. We wait for backend.
            // But we can send user_text. Backend logic: "Recv user_text -> cancel current -> next_turn"

            ws.send({
                type: "user_text",
                text: text,
                // We might need to send current turnId or just let backend handle it
            });
        },

        triggerInterrupt() {
            const ws = WebSocketService.getInstance();

            // 1. Immediate local stop (Barge-in experience)
            this.stopAudio("interrupt");
            this.assistantText = ""; // Optional: clear text on interrupt?
            this.addLog(`Sent interrupt`);

            // 2. Send signal
            ws.send({
                type: "interrupt",
                // Backend key: interrupt -> turnId++ -> discard old messages
            });

            // 3. Optimistic state
            this.backendState = "idle";
        },

        handleServerMessage(msg: Record<string, any>) {
            // 1. Filter stale messages
            const msgTurnId = msg.turn_id; // logic assumes backend sends turn_id on everything relevant
            if (typeof msgTurnId === 'number' && msgTurnId < this.turnId) {
                console.log(`Drop stale msg (msgTurn=${msgTurnId} < local=${this.turnId})`, msg);
                return;
            }

            // 2. State & Turn Update
            if (typeof msgTurnId === 'number' && msgTurnId > this.turnId) {
                this.turnId = msgTurnId;
            }

            switch (msg.type) {
                case "hello":
                    this.sessionInfo = {
                        sessionId: msg.session_id,
                        serverInstanceId: msg.server_instance_id,
                    };
                    this.turnId = msg.turn_id_reset || 0;
                    this.assistantText = "";
                    this.chatLog = [];
                    this.addLog(`Connected: ${msg.msg}`);
                    break;

                case "state_update":
                    this.backendState = msg.state;
                    break;

                case "assistant_reply":
                    this.assistantText = msg.text || "";
                    this.addLog(`Assistant: ${msg.text}`);
                    // If tts_url exists (legacy v0.1 logic), play it
                    if (msg.tts_url) {
                        this.playAudio(msg.tts_url);
                    }
                    break;

                case "audio_chunk":
                    // Protocol v0.1.1: Base64 audio chunk with strict turn filtering
                    // Logic: 
                    // 1. Advance local turnId if backend says so (max policy)
                    // 2. Only play if msg.turn_id matches exactly (or is newer if we adopt that policy, but strict equality is safer for anti-ghost)

                    if (typeof msg.turn_id === 'number') {
                        if (msg.turn_id > this.turnId) {
                            this.turnId = msg.turn_id;
                        }
                    }

                    if (msg.turn_id === this.turnId) {
                        if (msg.data) {
                            try {
                                // Decode Base64 -> Blob
                                const binaryString = window.atob(msg.data);
                                const len = binaryString.length;
                                const bytes = new Uint8Array(len);
                                for (let i = 0; i < len; i++) {
                                    bytes[i] = binaryString.charCodeAt(i);
                                }
                                // Use format hint if available, default to wav
                                const mime = msg.format === 'mp3' ? 'audio/mpeg' : 'audio/wav';
                                const blob = new Blob([bytes], { type: mime });
                                const url = URL.createObjectURL(blob);
                                this.playAudio(url);
                            } catch (e) {
                                console.error("Failed to decode audio chunk", e);
                            }
                        }
                    } else {
                        console.log(`Drop stale audio chunk (msgTurn=${msg.turn_id} != local=${this.turnId})`);
                    }
                    break;

                case "error":
                    this.addLog(`Error: ${msg.msg}`);
                    break;
            }
        },

        // Audio Helpers
        playAudio(url: string) {
            this.stopAudio("switch");
            const audio = new Audio(url);
            this.audioElement = audio;

            audio.onplay = () => { this.isPlaying = true; };
            audio.onended = () => { this.isPlaying = false; };
            audio.onerror = () => { this.isPlaying = false; };

            audio.play().catch(e => console.error("Audio play failed", e));
        },

        stopAudio(reason: string) {
            if (this.audioElement) {
                this.audioElement.pause();
                this.audioElement.currentTime = 0;
            }
            this.isPlaying = false;
            console.log(`Audio stopped: ${reason}`);
        },

        addLog(msg: string) {
            this.chatLog.unshift(`${new Date().toLocaleTimeString()} ${msg}`);
        }
    }
});
