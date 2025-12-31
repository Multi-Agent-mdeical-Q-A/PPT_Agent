type WebSocketMessage = Record<string, any>;

type MessageHandler = (msg: WebSocketMessage) => void;

export class WebSocketService {
    private static instance: WebSocketService;
    private ws: WebSocket | null = null;
    private messageHandler: MessageHandler | null = null;
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

    public connect(url?: string) {
        // Use env var or default
        const targetUrl = url || import.meta.env.VITE_WS_URL || "ws://127.0.0.1:8000/ws";

        if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
            console.log("WS already open/connecting");
            return;
        }

        this.url = targetUrl;
        console.log(`WS connecting -> ${targetUrl}`);
        const mySeq = ++this.connSeq;
        this.ws = new WebSocket(targetUrl);

        this.ws.onopen = () => {
            console.log("WS open");
            if (mySeq !== this.connSeq) return;  // 👈 忽略旧连接事件
            this.openHandler?.();
        };

        this.ws.onmessage = (evt) => {
            if (!this.messageHandler) return;

            try {
                if (typeof evt.data === "string") {
                    const msg = JSON.parse(evt.data);
                    this.messageHandler(msg);
                } else if (evt.data instanceof Blob) {
                    this.messageHandler({
                        type: 'audio_blob',
                        blob: evt.data
                    });
                }

            } catch (e) {
                console.error("WS parse error", e);
            }
        };

        this.ws.onclose = () => {
            console.log("WS close");
            if (mySeq !== this.connSeq) return;  // 👈 忽略旧连接事件
            this.closeHandler?.();
        };

        this.ws.onerror = (err) => {
            console.error("WS error", err);
            if (mySeq !== this.connSeq) return;  // 👈 忽略旧连接事件
            this.errorHandler?.(err);
        };
    }

    public disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }

    public isOpen() {
        return this.ws?.readyState === WebSocket.OPEN;
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
