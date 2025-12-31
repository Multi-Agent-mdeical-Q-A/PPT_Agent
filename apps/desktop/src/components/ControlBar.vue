<script setup lang="ts">
  import { ref, computed } from 'vue';

  const props = defineProps<{
    connected: boolean;
    onSend: (text: string) => void;
    onInterrupt: () => void;
  }>();

  const input = ref('hello backend');

  function handleSend() {
    if (input.value.trim()) {
      props.onSend(input.value);
    }
  }

  const canSend = computed(() => props.connected && input.value.trim().length > 0);
</script>

<template>
  <div class="control-bar">
    <input 
      v-model="input" 
      class="text-input"
      @keydown.enter="handleSend"
      placeholder="Type a message..."
      :disabled="!connected"
    />
    
    <button class="btn send-btn" :disabled="!canSend" @click="handleSend">
      Send
    </button>
    
    <button class="btn interrupt-btn" :disabled="!connected" @click="onInterrupt">
      Interrupt
    </button>
  </div>
</template>

<style scoped>
.control-bar {
  display: flex;
  gap: 12px;
  padding: 16px;
  background: white;
  border-top: 1px solid #eee;
  align-items: center;
}

.text-input {
  flex: 1;
  padding: 10px 16px;
  border-radius: 8px;
  border: 1px solid #ccc;
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s;
}

.text-input:focus {
  border-color: #2196f3;
}

.text-input:disabled {
  background: #f5f5f5;
  cursor: not-allowed;
}

.btn {
  padding: 10px 20px;
  border-radius: 8px;
  border: none;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.send-btn {
  background: #2196f3;
  color: white;
}

.interrupt-btn {
  background: #ff5252;
  color: white;
}
</style>
