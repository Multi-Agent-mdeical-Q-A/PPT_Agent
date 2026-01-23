<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
import { useAgentStore } from "../stores/agent/index";

const store = useAgentStore();

const listRef = ref<HTMLDivElement | null>(null);

// ✅ 自动滚动到底部（每次新消息进来）
watch(
  () => store.messages.length,
  async () => {
    await nextTick();
    const el = listRef.value;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }
);
</script>

<template>
  <div class="conversation-panel">
    <div class="messages-list" ref="listRef">
      <div v-if="!store.messages.length" class="placeholder">
        <h3>Start a conversation</h3>
      </div>
      <div
        v-for="m in store.messages"
        :key="m.id"
        class="message-bubble"
        :class="m.role"
      >
        <div class="role-label">{{ m.role }}</div>
        <div class="text">{{ m.text }}</div>
      </div>

    </div>

    <div class="debug-toggle">
      <details>
        <summary>Debug Logs</summary>
        <div class="debug-logs">
          <div v-for="(log, i) in store.debugLog" :key="i" class="log-item">
            {{ log }}
          </div>
        </div>
      </details>
    </div>
  </div>
</template>

<style scoped>
.conversation-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #252526;
  padding: 16px;
}

.messages-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 12px;
}

.placeholder {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #555;
}
.placeholder h3 {
  font-weight: normal;
  font-size: 16px;
}

.message-bubble {
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.4;
  max-width: 90%;
  word-wrap: break-word;
  position: relative;
}

.message-bubble.user {
  background: #0e639c;
  color: white;
  align-self: flex-end;
  border-bottom-right-radius: 2px;
}

.message-bubble.assistant {
  background: #3e3e42;
  color: #e0e0e0;
  align-self: flex-start;
  border-bottom-left-radius: 2px;
}

.role-label {
  font-size: 10px;
  opacity: 0.5;
  margin-bottom: 6px;
  text-transform: uppercase;
  font-weight: bold;
}

/* ✅ 引用效果 */
.quote-block {
  border-left: 3px solid rgba(255, 255, 255, 0.25);
  padding-left: 10px;
  margin-bottom: 8px;
  opacity: 0.9;
}
.quote-title {
  font-size: 10px;
  opacity: 0.7;
  margin-bottom: 4px;
}
.quote-text {
  font-size: 12px;
  opacity: 0.85;
  white-space: pre-wrap;
}

/* Debug Logs */
.debug-toggle {
  flex-shrink: 0;
  font-size: 11px;
  color: #666;
  border-top: 1px solid #333;
  padding-top: 8px;
}
.debug-toggle summary {
  cursor: pointer;
  margin-bottom: 4px;
}
.debug-logs {
  height: 120px;
  background: #111;
  border: 1px solid #333;
  padding: 8px;
  overflow-y: auto;
  font-family: monospace;
  border-radius: 4px;
}
.log-item {
  border-bottom: 1px solid #222;
  padding: 2px 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #00e676;
}
</style>
