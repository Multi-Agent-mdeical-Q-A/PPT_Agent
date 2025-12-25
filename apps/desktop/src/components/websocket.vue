<script setup lang="ts">
    import { ref, onMounted, onBeforeUnmount, computed } from "vue";
    
    type WSMessage =
      | { type: "hello"; msg?: string }
      | { type: "echo"; data?: any; recv?: any }
      | { type: "state_update"; generation_id?: number; state: "idle" | "thinking" | "speaking" | "listening" }
      | { type: "assistant_reply"; generation_id?: number; text?: string; tts_url?: string }
      | { type: "error"; msg?: string }
      | Record<string, any>;
    
    const WS_URL = "ws://127.0.0.1:8000/ws";
    
    // UI state
    const status = ref<"disconnected" | "connected" | "closed">("disconnected");
    const log = ref<string[]>([]);
    const input = ref("hello backend");
    
    // conversation state
    const currentGenerationId = ref<number>(0);
    const assistantText = ref<string>("");
    const backendState = ref<string>("idle");
    
    // websocket
    let ws: WebSocket | null = null;
    
    // audio
    let audio: HTMLAudioElement | null = null;
    const isPlaying = ref(false);
    
    function addLog(s: string) {
      log.value.unshift(`${new Date().toLocaleTimeString()} ${s}`);
    }
    
    function safeJsonParse(s: string): any {
      try {
        return JSON.parse(s);
      } catch {
        return null;
      }
    }
    
    function stopAudio(reason = "stop") {
      if (audio) {
        try {
          audio.pause();
          audio.currentTime = 0;
        } catch {}
      }
      isPlaying.value = false;
      addLog(`Audio ${reason}`);
    }
    
    function playUrl(url: string, gid: number) {
      stopAudio("switch");
    
      audio = new Audio(url);
    
      audio.onplay = () => {
        isPlaying.value = true;
        addLog(`Audio play (gid=${gid})`);
      };
    
      audio.onended = () => {
        isPlaying.value = false;
        addLog(`Audio ended (gid=${gid})`);
      };
    
      audio.onerror = () => {
        isPlaying.value = false;
        addLog(`Audio error (gid=${gid})`);
      };
    
      audio
        .play()
        .then(() => {})
        .catch((e) => {
          addLog(`Audio play() rejected: ${String(e)}`);
          console.error(e);
        });
    }
    
    function connect() {
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        addLog("WS already open/connecting");
        return;
      }
    
      addLog(`WS connecting -> ${WS_URL}`);
      ws = new WebSocket(WS_URL);
    
      ws.onopen = () => {
        status.value = "connected";
        addLog("WS open");
        // 可选：发 hello（如果后端需要会话初始化）
        // ws?.send(JSON.stringify({ type: "hello" }));
      };
    
      ws.onmessage = async (evt) => {

        addLog(`WS recv raw: ${evt.data}`);
        if (evt.data instanceof Blob) {
            const url = URL.createObjectURL(evt.data);
            const audio = new Audio(url);
            await audio.play();
            return;
        }
        const msg = safeJsonParse(String(evt.data)) as WSMessage | null;
        if (!msg) return;
    
        // 统一处理 generation_id：如果是旧 gid 的消息，丢弃（避免打断后旧音频/文本回来）
        const gid = typeof (msg as any).generation_id === "number" ? (msg as any).generation_id : undefined;
        if (gid !== undefined && gid < currentGenerationId.value) {
          addLog(`Drop stale msg (gid=${gid} < current=${currentGenerationId.value}) type=${(msg as any).type}`);
          return;
        }
    
        switch ((msg as any).type) {
          case "hello": {
            addLog(`Backend hello: ${(msg as any).msg ?? ""}`);
            break;
          }
    
          case "state_update": {
            if (gid !== undefined) currentGenerationId.value = gid;
            backendState.value = (msg as any).state;
            addLog(`State -> ${(msg as any).state} (gid=${currentGenerationId.value})`);
            break;
          }
    
          case "assistant_reply": {
            // 更新 gid
            if (gid !== undefined) currentGenerationId.value = gid;
    
            const text = (msg as any).text ?? "";
            const ttsUrl = (msg as any).tts_url ?? "";
    
            assistantText.value = text;
            addLog(`Assistant text (gid=${currentGenerationId.value}): ${text}`);
    
            if (ttsUrl) {
              playUrl(ttsUrl, currentGenerationId.value);
            } else {
              addLog("No tts_url in assistant_reply");
            }
            break;
          }
    
          case "error": {
            addLog(`Backend error: ${(msg as any).msg ?? ""}`);
            break;
          }
    
          default: {
            // 你也可以在这里处理 echo 或其它类型
            addLog(`WS msg type ${(msg as any).type ?? "unknown"}`);
          }
        }
      };
    
      ws.onerror = (err) => {
        addLog("WS error (see console)");
        console.error(err);
      };
    
      ws.onclose = () => {
        status.value = "closed";
        addLog("WS close");
      };
    }
    
    function disconnect() {
      ws?.close();
      ws = null;
      status.value = "closed";
      addLog("WS disconnect()");
    }
    
    function sendText() {
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        addLog("WS not open");
        return;
      }
    
      // 每次发起新一轮对话，本地先推进 generation_id（确保旧消息不会干扰）
      currentGenerationId.value += 1;
      const gid = currentGenerationId.value;
    
      const payload = {
        type: "user_text",
        generation_id: gid,
        text: input.value,
      };
    
      ws.send(JSON.stringify(payload));
      addLog(`WS send user_text (gid=${gid}): ${input.value}`);
    
      // 用户发起后，先把状态置为 thinking（后端也会发 state_update）
      backendState.value = "thinking";
    }
    
    function interrupt() {
      // 本地硬打断：立刻停音频，并推进 generation_id（丢弃旧消息）
      currentGenerationId.value += 1;
      const gid = currentGenerationId.value;
    
      stopAudio("interrupt");
      assistantText.value = "";
    
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "interrupt", generation_id: gid }));
        addLog(`WS send interrupt (gid=${gid})`);
      } else {
        addLog("WS not open, interrupt only local");
      }
    
      backendState.value = "idle";
    }
    
    const canSend = computed(() => status.value === "connected" && input.value.trim().length > 0);
    const canInterrupt = computed(() => status.value === "connected" && isPlaying.value);
    
    onMounted(() => connect());
    onBeforeUnmount(() => {
      stopAudio("unmount");
      disconnect();
    });
    </script>
    
    <template>
      <div style="padding: 16px">
        <div style="display: flex; align-items: center; gap: 12px">
          <h3 style="margin: 0">WS status: {{ status }}</h3>
          <div>Backend state: <b>{{ backendState }}</b></div>
          <div>gid: <b>{{ currentGenerationId }}</b></div>
    
          <button @click="connect" style="margin-left: auto">Connect</button>
          <button @click="disconnect">Disconnect</button>
        </div>
    
        <div style="margin-top: 12px; display: flex; gap: 8px; align-items: center">
          <input v-model="input" style="width: 360px" @keyup.enter="sendText" />
          <button :disabled="!canSend" @click="sendText">Send</button>
          <button :disabled="!canInterrupt" @click="interrupt">Interrupt</button>
        </div>
    
        <div style="margin-top: 12px; padding: 8px; border: 1px solid #ddd">
          <div style="font-weight: 600; margin-bottom: 6px">Assistant</div>
          <div style="white-space: pre-wrap">{{ assistantText || "—" }}</div>
        </div>
    
        <div style="margin-top: 12px; height: 260px; overflow: auto; border: 1px solid #ccc; padding: 8px">
          <div v-for="(l, i) in log" :key="i">{{ l }}</div>
        </div>
      </div>
    </template>
    