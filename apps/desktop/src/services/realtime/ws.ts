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
        this.ws = localWs;

        localWs.onopen = () => {
            if (mySeq !== this.connSeq || this.ws !== localWs) return;
            console.log("WS open");
            this.openHandler?.();
        };

        localWs.onmessage = (evt) => {
            if (mySeq !== this.connSeq || this.ws !== localWs) return;
            if (!this.messageHandler) return;

            // ✅ v0.1 协议：只接受 JSON 文本
            if (typeof evt.data !== "string") {
                console.warn("WS non-text message ignored (expected JSON string).", evt.data);
                return;
            }

            try {
                const msg = JSON.parse(evt.data);
                this.messageHandler(msg);
            } catch (e) {
                console.error("WS JSON parse error", e, evt.data);
            }
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
