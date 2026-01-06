<script setup lang="ts">
import { computed } from "vue";
import { useAgentStore } from "../stores/agent/index";

const store = useAgentStore();

const mouthScaleY = computed(() => {
  return Math.min(1.2, 0.15 + store.mouthOpen * 0.9);
});

// ✅ 来自 pinia getter（统一推导）
const uiState = computed(() => store.uiState);

const isSpeaking = computed(() => uiState.value === "speaking");
const isThinking = computed(() => uiState.value === "thinking");
</script>

<template>
  <div class="avatar-container">
    <div class="avatar-wrapper" :class="{ speaking: isSpeaking, thinking: isThinking }">
      <div class="face">
        <div class="eye left" :class="{ blink: isThinking }"></div>
        <div class="eye right" :class="{ blink: isThinking }"></div>

        <div class="mouth" :style="{ transform: `scaleY(${mouthScaleY})` }"></div>
      </div>
    </div>

    <div class="status-indicator">State: {{ uiState }}</div>

    <div class="debug-hud">
      <div>Mouth: {{ store.mouthOpen.toFixed(2) }}</div>
      <div>Turn: {{ store.turnId }}</div>
      <div>Audio: {{ store.isPlaying ? "Playing" : "Stop" }}</div>
    </div>
  </div>
</template>

<style scoped>
/* 你原来的样式保持不变即可 */
.avatar-container {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1a1a1a 0%, #2a2a2a 100%);
  color: white;
  position: relative;
}

.avatar-wrapper {
  width: 200px;
  height: 200px;
  border-radius: 50%;
  overflow: hidden;
  border: 4px solid #555;
  background: #333;
  transition: border-color 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.avatar-wrapper.speaking {
  border-color: #4caf50;
}
.avatar-wrapper.thinking {
  border-color: #2196f3;
  animation: pulse-border 2s infinite;
}

.face {
  width: 60%;
  height: 60%;
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: space-between;
  padding: 20px 0;
}

.eye {
  width: 20px;
  height: 20px;
  background: white;
  border-radius: 50%;
  position: absolute;
  top: 20px;
}
.eye.left {
  left: 20px;
}
.eye.right {
  right: 20px;
}

.eye.blink {
  animation: blink 1s infinite alternate;
}

.mouth {
  width: 60px;
  height: 30px;
  background: #ff5252;
  border-radius: 15px;
  margin-top: auto;
  transition: transform 0.05s ease-out;
  transform-origin: center bottom;
}

.status-indicator {
  margin-top: 20px;
  font-size: 14px;
  opacity: 0.7;
  text-transform: uppercase;
  letter-spacing: 1px;
}

.debug-hud {
  position: absolute;
  bottom: 10px;
  right: 10px;
  font-family: monospace;
  font-size: 10px;
  color: #00e676;
  background: rgba(0, 0, 0, 0.6);
  padding: 4px;
  border-radius: 4px;
  pointer-events: none;
  text-align: right;
}

@keyframes pulse-border {
  0% {
    box-shadow: 0 0 0 0 rgba(33, 150, 243, 0.4);
  }
  70% {
    box-shadow: 0 0 0 10px rgba(33, 150, 243, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(33, 150, 243, 0);
  }
}

@keyframes blink {
  0% {
    transform: scaleY(1);
  }
  90% {
    transform: scaleY(1);
  }
  100% {
    transform: scaleY(0.1);
  }
}
</style>
