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

    // seq for audio chunks
    audioSeqExpected: number;

    // currently playing blob url (for <audio> path)
    currentAudioUrl: string | null;

    // lipsync
    mouthOpen: number; // 0..1

    // audio mode flags
    audioStreaming: boolean; // streaming active (MSE/PCM)
    audioIsPcm: boolean; // current audio is pcm_s16le
}

export type WsCtx = {
    // state
    turnId: number;
    backendState: BackendState;
    sessionInfo: SessionInfo | null;

    // text
    messages: ChatMessage[];
    debugLog: string[];
    assistantText: string;

    // audio
    audioStreaming: boolean;
    audioIsPcm: boolean;
    audioChunks: Uint8Array[];
    audioMimeType: string;
    audioSeqExpected: number;

    // effects
    addDebug: (msg: string) => void;
    playBufferedAudio: () => void;
    stopAudio: (reason: string) => void;

    // MSE streaming hooks
    startStream: (mime: string) => boolean;
    appendStreamChunk: (chunk: Uint8Array) => void;
    endStream: () => void;
    cancelStream: () => void;

    // PCM streaming hooks
    startPcmStream: (sampleRate: number, channels: number) => boolean;
    appendPcmChunk: (chunk: Uint8Array) => void;
    endPcmStream: () => void;
    cancelPcmStream: () => void;
};

export type AudioMetric = {
    beginTs: number;
    firstChunkTs?: number;
    chunkCount: number;
    totalBytes: number;
    lastSeq?: number;
};

export type AudioCtx = {
    // state fields used
    isPlaying: boolean;
    audioElement: HTMLAudioElement | null;
    audioChunks: Uint8Array[];
    audioMimeType: string;
    currentAudioUrl: string | null;

    audioSeqExpected: number;

    // side effects
    addDebug: (msg: string) => void;
    setIsPlaying: (v: boolean) => void;
    setAudioElement: (el: HTMLAudioElement | null) => void;
    setCurrentAudioUrl: (u: string | null) => void;

    // reset buffer helpers
    resetAudioBuffer: () => void;
};
