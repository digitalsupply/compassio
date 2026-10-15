<script setup lang="ts">
import { computed } from 'vue'
import { useNotifyStore } from '@/stores/notify'

const notify = useNotifyStore()
const hasCritical = computed(() => notify.criticalUnread.length > 0)
</script>

<template>
  <div v-if="hasCritical" class="critical-banner">
    <div class="inner">
      <span class="label">严重预警</span>
      <span class="text">
        {{ notify.criticalUnread[0].title }}：{{ notify.criticalUnread[0].body }}
      </span>
      <span v-if="notify.criticalUnread.length > 1" class="more">
        等 {{ notify.criticalUnread.length }} 条
      </span>
    </div>
  </div>
</template>

<style scoped>
.critical-banner {
  background: #b91c1c;
  color: #fff;
  padding: 10px 24px;
  font-size: 14px;
}
.inner {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.label {
  font-weight: 700;
  background: #fff;
  color: #b91c1c;
  padding: 2px 8px;
  border-radius: 4px;
}
.text {
  flex: 1;
}
.more {
  opacity: 0.9;
}
@media print {
  .critical-banner {
    display: none !important;
  }
}
</style>
