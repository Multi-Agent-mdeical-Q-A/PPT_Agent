type WebSocketMessage = Record<string, any>;
type MessageHandler = (msg: WebSocketMessage) => void;

// Binary frame format:
// 4 bytes magic 'AUD0'
// u32le turn_id
// u32le seq
// ... payload (raw bytes)
const AUD_MAGIC = 0x30445541; // 'AUD0' little-endian in DataView getUint32(0,true)

function parseAudioFrame(u8: Uint8Array): WebSocketMessage | null {
    if (u8.byteLength < 12) return null;
    const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
    const magic = dv.getUint32(0, true);
    if (magic !== AUD_MAGIC) return null;
    const turn_id = dv.getUint32(4, true);
    const seq = dv.getUint32(8, true);
    const payload = u8.subarray(12);
    return { type: "audio_chunk_bin", turn_id, seq, payload };
}

export class WebSocketService {
    private static instance: WebSocketService;

    private ws: WebSocket | null = null;
    private messageHandler: MessageHandler | null = null;

    private url: string = "";
    private connSeq = 0;

    private openHandler: (() => void) | null = null;
    private closeHandler: (() => void) | null = null;
    private errorHandler: ((err: Event) => void) | null = null;

    private constructor() {}

    public static getInstance(): WebSocketService {
        if (!WebSocketService.instance) {
            WebSocketService.instance = new WebSocketService();
        }
        return WebSocketService.instance;
    }

    public getUrl() {
        return this.url;
    }

    public connect(url?: string) {
        const targetUrl =
            url ||
            this.url ||
            import.meta.env.VITE_WS_URL ||
            "ws://127.0.0.1:8000/ws";

        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
            console.log("WS already open/connecting");
            return;
        }

        this.url = targetUrl;
        console.log(`WS connecting -> ${targetUrl}`);

        const mySeq = ++this.connSeq;
        const localWs = new WebSocket(targetUrl);
        // ✅ important for binary frames
        localWs.binaryType = "arraybuffer";

        this.ws = localWs;

        localWs.onopen = () => {
            if (mySeq !== this.connSeq || this.ws !== localWs) return;
            console.log("WS open");
            this.openHandler?.();
        };

        localWs.onmessage = async (evt) => {
            if (mySeq !== this.connSeq || this.ws !== localWs) return;
            if (!this.messageHandler) return;

            const handleJson = (s: string) => {
                try {
                    const msg = JSON.parse(s);
                    this.messageHandler?.(msg);
                } catch (e) {
                    console.error("WS JSON parse error", e, s);
                }
            };

            // 1) Text
            if (typeof evt.data === "string") {
                handleJson(evt.data);
                return;
            }

            const handleBinary = (u8: Uint8Array) => {
                // try json-bytes first
                try {
                    const s = new TextDecoder("utf-8", { fatal: true }).decode(u8);
                    handleJson(s);
                    return;
                } catch {
                    // then try audio frame
                    const audioMsg = parseAudioFrame(u8);
                    if (audioMsg) {
                        this.messageHandler?.(audioMsg);
                        return;
                    }

                    // fallback
                    this.messageHandler?.({ type: "ws_binary", bytes: u8.length });
                }
            };

            // 2) ArrayBuffer
            if (evt.data instanceof ArrayBuffer) {
                handleBinary(new Uint8Array(evt.data));
                return;
            }

            // 3) Blob
            if (evt.data instanceof Blob) {
                const buf = await evt.data.arrayBuffer();
                handleBinary(new Uint8Array(buf));
                return;
            }

            console.warn("WS unknown message type", evt.data);
        };

        localWs.onclose = () => {
            if (mySeq !== this.connSeq || this.ws !== localWs) return;
            console.log("WS close");
            this.closeHandler?.();
        };

        localWs.onerror = (err) => {
            if (mySeq !== this.connSeq || this.ws !== localWs) return;
            console.error("WS error", err);
            this.errorHandler?.(err);
        };
    }

    public disconnect() {
        if (this.ws) {
            this.connSeq++;
            try {
                this.ws.close();
            } catch (e) {
                console.warn("WS close error", e);
            }
            this.ws = null;
        }
    }

    public isOpen() {
        return this.ws?.readyState === WebSocket.OPEN;
    }

    public isConnecting() {
        return this.ws?.readyState === WebSocket.CONNECTING;
    }

    public send(msg: WebSocketMessage) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(msg));
        } else {
            console.warn("WS not open, cannot send", msg);
        }
    }

    public onMessage(handler: MessageHandler) {
        this.messageHandler = handler;
    }
    public onOpen(handler: () => void) {
        this.openHandler = handler;
    }
    public onClose(handler: () => void) {
        this.closeHandler = handler;
    }
    public onError(handler: (err: Event) => void) {
        this.errorHandler = handler;
    }
}
