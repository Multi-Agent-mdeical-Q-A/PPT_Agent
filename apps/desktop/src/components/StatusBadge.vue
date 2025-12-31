<script setup lang="ts">
import { computed } from 'vue';

const props = defineProps<{
  state: string;
}>();

const badgeStyle = computed(() => {
  switch (props.state) {
    case 'idle':
      return { backgroundColor: '#e0e0e0', color: '#666' };
    case 'thinking':
      return { backgroundColor: '#ffe082', color: '#e65100' };
    case 'speaking':
      return { backgroundColor: '#81d4fa', color: '#01579b' };
    case 'listening':
      return { backgroundColor: '#a5d6a7', color: '#1b5e20' };
    default:
      return { backgroundColor: '#f5f5f5', color: '#999' };
  }
});
</script>

<template>
  <span class="status-badge" :style="badgeStyle">
    <span class="dot">●</span> {{ state }}
  </span>
</template>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 12px;
  border-radius: 16px;
  font-size: 13px;
  font-weight: 600;
  text-transform: uppercase;
  gap: 6px;
  transition: all 0.2s ease;
}

.dot {
  font-size: 10px;
}
</style>
