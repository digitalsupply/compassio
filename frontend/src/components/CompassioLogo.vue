<script setup lang="ts">
defineProps<{ size?: number }>()
</script>

<template>
  <svg
    class="compass-logo"
    :width="size || 40"
    :height="size || 40"
    viewBox="0 0 100 100"
    fill="none"
    stroke="currentColor"
    stroke-width="6"
    stroke-linecap="round"
    stroke-linejoin="round"
  >
    <circle cx="50" cy="50" r="40" />
    <path d="M50 18v8M50 74v8M18 50h8M74 50h8" />
    <path d="M50 50L64 36" class="needle" />
    <circle cx="50" cy="50" r="4" fill="currentColor" stroke="none" />
  </svg>
</template>

<style scoped>
.compass-logo {
  color: #3b82f6;
}
.needle {
  color: #f59e0b;
}
</style>
