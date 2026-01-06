// src/stores/agent/types.ts
export type ConnectionStatus = "disconnected" | "connected" | "connecting" | "closed";
export type BackendState = "idle" | "thinking" | "speaking" | "listening";

export type SessionInfo = {
    sessionId: string;
    serverInstanceId: string;
};

export interface ChatMessage {
    id: string;
    role: "user" | "assistant";
    text: string;
    turnId: number;
    timestamp: number;
}

export interface AgentState {
    connectionStatus: ConnectionStatus;
    backendState: BackendState;
    turnId: number;
    sessionInfo: SessionInfo | null;

    messages: ChatMessage[];
    debugLog: string[];
    assistantText: string;

    // audio receive/playback
    isPlaying: boolean;
    audioElement: HTMLAudioElement | null;
    audioChunks: Uint8Array[];
    audioMimeType: string;

    audioTurnId: number | null;
    audioSeqExpected: number;

    currentAudioUrl: string | null;

    // lipsync
    mouthOpen: number; // 0..1
}

export type WsCtx = {
    // state
    turnId: number;
    backendState: BackendState;
    sessionInfo: SessionInfo | null;

    messages: ChatMessage[];
    debugLog: string[];
    assistantText: string;

    audioChunks: Uint8Array[];
    audioMimeType: string;
    audioTurnId: number | null;
    audioSeqExpected: number;

    // effects
    addDebug: (msg: string) => void;
    stopAudio: (reason: string) => void;
    playBufferedAudio: () => void;
};

export type AudioCtx = {
    // state fields used
    isPlaying: boolean;
    audioElement: HTMLAudioElement | null;
    audioChunks: Uint8Array[];
    audioMimeType: string;
    currentAudioUrl: string | null;

    audioTurnId: number | null;
    audioSeqExpected: number;

    // side effects
    addDebug: (msg: string) => void;
    setIsPlaying: (v: boolean) => void;
    setAudioElement: (el: HTMLAudioElement | null) => void;
    setCurrentAudioUrl: (u: string | null) => void;

    // reset buffer helpers
    resetAudioBuffer: () => void;
};