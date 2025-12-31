<script setup lang="ts">
import { ref } from 'vue';

// Use a placeholder image from a public URL or a local asset
// For v0.1, we use a simple generic avatar or placeholder
const avatarUrl = ref('https://api.dicebear.com/7.x/avataaars/svg?seed=lala');

const isSpeaking = ref(false); // Can be linked to store state later
</script>

<template>
  <div class="avatar-container">
    <div class="avatar-wrapper" :class="{ speaking: isSpeaking }">
      <img :src="avatarUrl" alt="Avatar" />
    </div>
    <div class="status-indicator">
       Digital Human v0.1
    </div>
  </div>
</template>

<style scoped>
.avatar-container {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1a1a1a 0%, #2a2a2a 100%);
  color: white;
}

.avatar-wrapper {
  width: 200px;
  height: 200px;
  border-radius: 50%;
  overflow: hidden;
  border: 4px solid #4caf50;
  transition: transform 0.2s;
}

.avatar-wrapper.speaking {
  animation: pulse 1s infinite;
  border-color: #00e676;
}

img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.status-indicator {
  margin-top: 20px;
  font-size: 14px;
  opacity: 0.7;
}

@keyframes pulse {
  0% { transform: scale(1); box-shadow: 0 0 0 0 rgba(76, 175, 80, 0.7); }
  70% { transform: scale(1.05); box-shadow: 0 0 0 10px rgba(76, 175, 80, 0); }
  100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(76, 175, 80, 0); }
}
</style>
