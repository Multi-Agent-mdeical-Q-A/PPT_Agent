<script setup lang="ts">
import { onMounted, onBeforeUnmount } from 'vue';
import { useAgentStore } from '../stores/agent';
import ControlBar from '../components/ControlBar.vue';
import StatusBadge from '../components/StatusBadge.vue';
import SlideViewer from '../components/SlideViewer.vue';
import Avatar from '../components/Avatar.vue';

const store = useAgentStore();

onMounted(() => {
  store.connect();
});

onBeforeUnmount(() => {
  store.disconnect();
});
</script>

<template>
  <div class="main-layout">
    <!-- Main Content Area -->
    <div class="content-area">
      <!-- Left: Slide Viewer -->
      <div class="slide-viewer">
        <SlideViewer />
      </div>

      <!-- Right: Avatar & Logs -->
      <div class="sidebar">
        <!-- Top-Right: Avatar -->
        <div class="avatar-area">
          <Avatar />
        </div>

        <!-- Middle-Right: Chat/Log -->
        <div class="chat-area">
          <div v-if="store.assistantText" class="assistant-bubble">
            {{ store.assistantText }}
          </div>
          <div class="log-stream">
             <div v-for="(log, i) in store.chatLog" :key="i" class="log-item">
               {{ log }}
             </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Bottom Status Bar -->
    <div class="status-header">
       <div class="status-left" @click="store.reconnect()" title="Click to Reconnect" style="cursor: pointer">
         <div class="connection-status" :class="store.connectionStatus"></div>
         <span>{{ store.connectionStatus }}</span>
       </div>
       <div class="status-center">
         <StatusBadge :state="store.backendState" />
       </div>
       <div class="status-right">
         Turn: {{ store.turnId }} | Session: {{ store.sessionInfo?.sessionId?.substring(0,6) || '-' }}
       </div>
    </div>

    <!-- Bottom Controls -->
    <ControlBar 
      :connected="store.connectionStatus === 'connected'"
      :onSend="store.sendUserText"
      :onInterrupt="store.triggerInterrupt"
    />
  </div>
</template>

<style scoped>
.main-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #f0f2f5;
  color: #333;
}

.content-area {
  flex: 1;
  display: flex;
  overflow: hidden;
  padding: 16px;
  gap: 16px;
  min-width: 0;              /* ✅ 允许子项在 flex 中收缩 */
}

.slide-viewer {
  flex: 3 1 0;               /* ✅ 左边吃剩余空间；0=更稳定的分配 */
  min-width: 0;              /* ✅ 关键：避免被内部内容“撑坏” */
  overflow: hidden;
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.05);
}

/* 确保 SlideViewer 组件自身撑满 */
.slide-viewer :deep(.slide-viewer-container) {
  width: 100%;
  height: 100%;
}

.sidebar {
  flex: 0 0 360px;           /* ✅ 固定 sidebar 宽度（你可以调 320/360/400） */
  min-width: 320px;          /* ✅ 双保险 */
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow: hidden;          /* ✅ 防止内部撑开 */
}

.avatar-area {
  flex: 0 0 240px; /* Fixed height for Avatar */
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.05);
  display: flex;
  align-items: center;
  justify-content: center;
}

.chat-area {
  flex: 1;
  background: white;
  border-radius: 12px;
  padding: 12px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.05);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.assistant-bubble {
  padding: 12px;
  background: #e3f2fd;
  color: #0d47a1;
  border-radius: 8px;
  margin-bottom: 12px;
  font-weight: 500;
  line-height: 1.5;
}

.log-stream {
  flex: 1;
  overflow-y: auto;
  font-family: monospace;
  font-size: 12px;
  color: #666;
}

.log-item {
  padding: 2px 0;
  border-bottom: 1px solid #f0f0f0;
}

.placeholder {
  text-align: center;
  color: #999;
}

.placeholder h3 { margin: 0; color: #ccc; }

.status-header {
  height: 32px;
  background: white;
  border-top: 1px solid #ddd;
  display: flex;
  align-items: center;
  padding: 0 16px;
  justify-content: space-between;
  font-size: 12px;
  color: #666;
}

.status-left {
  display: flex;
  align-items: center;
  gap: 6px;
}

.connection-status {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ccc;
}
.connection-status.connected { background: #4caf50; }
.connection-status.disconnected { background: #f44336; }

</style>
