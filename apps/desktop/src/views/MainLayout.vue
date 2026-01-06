<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from "vue";
import { useAgentStore } from "../stores/agent/index";
import SlideViewer from "../components/SlideViewer.vue";
import Avatar from "../components/Avatar.vue";
import ConversationPanel from "../components/ConversationPanel.vue"

const store = useAgentStore();
const inputText = ref("");

const slideViewerRef = ref<any>(null);
const handlePrev = () => slideViewerRef.value?.prevPage();
const handleNext = () => slideViewerRef.value?.nextPage();

const sendText = () => {
  if (!inputText.value.trim()) return;
  store.sendUserText(inputText.value);
  inputText.value = "";
};

onMounted(() => store.connect());
onBeforeUnmount(() => store.disconnect());
</script>

<template>
  <div class="main-layout">
    <div class="left-column">
      <div class="slide-container">
        <SlideViewer ref="slideViewerRef" />
      </div>

      <div class="status-bar">
        <div
          class="status-left"
          @click="store.connectionStatus === 'connecting' ? null : store.reconnect()"
          title="Click to Reconnect"
          :style="{ opacity: store.connectionStatus === 'connecting' ? 0.5 : 1, cursor: store.connectionStatus === 'connecting' ? 'not-allowed' : 'pointer' }"
        >
          <div class="connection-dot" :class="store.connectionStatus"></div>
          <span>{{ store.connectionStatus }}</span>
        </div>

        <div class="status-center-controls">
          <template v-if="slideViewerRef && slideViewerRef.totalPages > 0">
            <button
              class="nav-btn"
              @click="handlePrev"
              :disabled="slideViewerRef.currentPage <= 1 || slideViewerRef.rendering"
            >
              Prev
            </button>

            <span class="page-info">
              {{ slideViewerRef.currentPage }} / {{ slideViewerRef.totalPages }}
              <span v-if="slideViewerRef.rendering" style="opacity: 0.7; font-size: 10px"
                >(loading...)</span
              >
            </span>

            <button
              class="nav-btn"
              @click="handleNext"
              :disabled="slideViewerRef.currentPage >= slideViewerRef.totalPages || slideViewerRef.rendering"
            >
              Next
            </button>
          </template>

          <template v-else>
            <span class="page-info" style="opacity: 0.7">No slides</span>
          </template>
        </div>

        <div class="status-right">
          Turn: {{ store.turnId }} | Session:
          {{ store.sessionInfo?.sessionId?.substring(0, 6) || "-" }}
        </div>
      </div>

      <div class="control-area">
        <div class="input-wrapper">
          <input
            v-model="inputText"
            @keyup.enter="sendText"
            placeholder="Type a message..."
            :disabled="store.connectionStatus !== 'connected'"
          />
          <button
            @click="sendText"
            :disabled="store.connectionStatus !== 'connected' || !inputText"
            class="send-btn"
          >
            Send
          </button>
          <button @click="store.triggerInterrupt()" class="interrupt-btn" title="Stop Speaking">
            Stop
          </button>
        </div>
      </div>
    </div>

    <div class="right-column">
      <div class="avatar-area">
        <Avatar />
      </div>

      <!-- ✅ 替代原 chat-panel -->
      <ConversationPanel />
    </div>
  </div>
</template>

<style scoped>
/* 你的样式基本不需要变；保留原来的 MainLayout 样式即可 */
.main-layout {
  display: flex;
  height: 100vh;
  width: 100vw;
  background: #1e1e1e;
  color: #e0e0e0;
  overflow: hidden;
  min-width: 1024px;
}

.left-column {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  border-right: 1px solid #333;
}

.slide-container {
  flex: 1;
  position: relative;
  background: black;
  overflow: hidden;
  display: flex;
}

.slide-container :deep(.slide-viewer-container) {
  width: 100%;
  height: 100%;
}

.status-bar {
  height: 48px;
  background: #252526;
  border-top: 1px solid #333;
  border-bottom: 1px solid #333;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  font-size: 11px;
  color: #888;
  font-family: monospace;
  flex-shrink: 0;
}

.status-left {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.connection-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #555;
}
.connection-dot.connected {
  background: #4caf50;
  box-shadow: 0 0 5px #4caf50;
}
.connection-dot.disconnected {
  background: #f44336;
}

.status-center-controls {
  display: flex;
  align-items: center;
  gap: 12px;
}

.nav-btn {
  background: #3e3e42;
  color: #e0e0e0;
  border: 1px solid #555;
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.2s;
}
.nav-btn:hover:not(:disabled) {
  background: #505055;
}
.nav-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.page-info {
  color: #ccc;
  font-weight: bold;
  min-width: 60px;
  text-align: center;
}

.control-area {
  height: 80px;
  background: #1e1e1e;
  padding: 0 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.input-wrapper {
  width: 100%;
  max-width: 800px;
  display: flex;
  gap: 12px;
  background: #2d2d2d;
  padding: 8px;
  border-radius: 8px;
  border: 1px solid #3e3e3e;
}

input {
  flex: 1;
  background: transparent;
  border: none;
  color: white;
  font-size: 14px;
  padding: 0 8px;
  outline: none;
}

button {
  padding: 8px 16px;
  border-radius: 6px;
  border: none;
  font-weight: 600;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
}

.send-btn {
  background: #007acc;
  color: white;
}
.send-btn:hover:not(:disabled) {
  background: #0062a3;
}
.send-btn:disabled {
  background: #444;
  color: #888;
  cursor: not-allowed;
}

.interrupt-btn {
  background: #3a3a3a;
  color: #ff6b6b;
  border: 1px solid #333;
}
.interrupt-btn:hover {
  background: #4a1a1a;
  border-color: #ff6b6b;
}

.right-column {
  width: 380px;
  display: flex;
  flex-direction: column;
  background: #252526;
  border-left: 1px solid #333;
  flex-shrink: 0;
}

.avatar-area {
  height: 280px;
  background: #1e1e1e;
  border-bottom: 1px solid #333;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
</style>
