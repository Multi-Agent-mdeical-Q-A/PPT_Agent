type WebSocketMessage = Record<string, any>;
type MessageHandler = (msg: WebSocketMessage) => void;

export class WebSocketService {
    private static instance: WebSocketService;

    private ws: WebSocket | null = null;
    private messageHandler: MessageHandler | null = null;

    // ✅ 用起来：记住最近一次成功/尝试连接的 url，reconnect 可复用
    private url: string = "";

    private connSeq = 0;

    private openHandler: (() => void) | null = null;
    private closeHandler: (() => void) | null = null;
    private errorHandler: ((err: Event) => void) | null = null;

    private constructor() { }

    private _handleJson = (s: string) => {
        try {
            const msg = JSON.parse(s);
            this.messageHandler?.(msg);
        } catch (e) {
            console.error("WS JSON parse error", e, s);
        }
    };

    private _tryHandleBinary = (buf: ArrayBuffer): boolean => {
        const u8 = new Uint8Array(buf);
        if (u8.length < 12) return false;

        // "AUD0" magic: 0x41 0x55 0x44 0x30
        if (u8[0] === 0x41 && u8[1] === 0x55 && u8[2] === 0x44 && u8[3] === 0x30) {
            const dv = new DataView(buf);
            const turn_id = dv.getUint32(4, true);
            const seq = dv.getUint32(8, true);
            const payload = new Uint8Array(buf, 12);

            // 交给上层：wsHandlers.ts 里新增 case "audio_chunk_bin"
            this.messageHandler?.({
                type: "audio_chunk_bin",
                turn_id,
                seq,
                payload,
            });
            return true;
        }
        return false;
    };

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
        // ✅ 优先级：参数 > 上次 url > env > default
        const targetUrl =
            url ||
            this.url ||
            import.meta.env.VITE_WS_URL ||
            "ws://127.0.0.1:8000/ws";

        // ✅ 已连接/正在连接：直接返回（不重建连接）
        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
            console.log("WS already open/connecting");
            return;
        }

        this.url = targetUrl;
        console.log(`WS connecting -> ${targetUrl}`);

        const mySeq = ++this.connSeq;
        const localWs = new WebSocket(targetUrl);
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
            // ✅ 1) 正常文本 JSON
            if (typeof evt.data === "string") {
                this._handleJson(evt.data);
                return;
            }

            // ✅ 2) ArrayBuffer：可能是 json-bytes，也可能是真二进制音频帧
            if (evt.data instanceof ArrayBuffer) {
                // 2.1 优先按二进制音频帧处理
                if (this._tryHandleBinary(evt.data)) return;

                // 2.2 fallback：当 UTF-8 JSON bytes 解码
                try {
                    const s = new TextDecoder("utf-8", { fatal: true }).decode(new Uint8Array(evt.data));
                    this._handleJson(s);
                    return;
                } catch {
                    this.messageHandler?.({ type: "ws_binary", bytes: (evt.data as ArrayBuffer).byteLength });
                    return;
                }
            }

            // ✅ 3) Blob：读成 ArrayBuffer 再走同样逻辑
            if (evt.data instanceof Blob) {
                const buf = await evt.data.arrayBuffer();

                if (this._tryHandleBinary(buf)) return;

                try {
                    const s = new TextDecoder("utf-8", { fatal: true }).decode(new Uint8Array(buf));
                    this._handleJson(s);
                    return;
                } catch {
                    this.messageHandler?.({ type: "ws_binary", bytes: buf.byteLength });
                    return;
                }
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
            // 关键：让当前 ws 的 onopen/onmessage 全部失效
            this.connSeq++;

            try {
                this.ws.close(); // CONNECTING 也可以 close
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
