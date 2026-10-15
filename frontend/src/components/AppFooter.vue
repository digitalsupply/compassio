<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
const auth = useAuthStore()
</script>

<template>
  <footer v-if="auth.isLoggedIn" class="app-footer">
    <p>本系统结果属于发展性筛查参考，不构成医学诊断。</p>
    <p class="copy">Compassio © 2026 提前指引，向阳成长。</p>
  </footer>
</template>

<style scoped>
.app-footer {
  text-align: center;
  padding: 20px;
  color: #6b7280;
  font-size: 13px;
  background: #f9fafb;
  border-top: 1px solid #e5e7eb;
}
.copy {
  margin-top: 4px;
  font-size: 12px;
  color: #9ca3af;
}
@media print {
  .app-footer {
    background: transparent;
    border: none;
    font-size: 11px;
    padding: 8px 0;
  }
}
</style>
