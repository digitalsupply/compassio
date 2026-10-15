<script setup lang="ts">
import { onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import AppFooter from '@/components/AppFooter.vue'
import CriticalBanner from '@/components/CriticalBanner.vue'
import { useAuthStore } from '@/stores/auth'
import { useNotifyStore } from '@/stores/notify'

const auth = useAuthStore()
const notify = useNotifyStore()
const route = useRoute()

let timer: number | undefined

function startPolling() {
  if (auth.isAdmin) {
    notify.pollAndAlert()
    timer = window.setInterval(() => notify.pollAndAlert(), 5000)
  }
}

function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = undefined
  }
}

watch(
  () => auth.isLoggedIn,
  (loggedIn) => {
    stopPolling()
    if (loggedIn && auth.isAdmin) startPolling()
  },
  { immediate: true }
)

onMounted(() => {
  if (auth.isLoggedIn && auth.isAdmin) startPolling()
})
onUnmounted(stopPolling)
</script>

<template>
  <div class="app-wrapper">
    <AppHeader />
    <CriticalBanner v-if="auth.isAdmin" />
    <main class="app-main">
      <router-view :key="route.fullPath" />
    </main>
    <AppFooter />
  </div>
</template>

<style>
* {
  box-sizing: border-box;
}
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial,
    'Noto Sans SC', sans-serif;
  background: #f3f4f6;
  color: #1f2937;
}
.app-wrapper {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}
.app-main {
  flex: 1;
  padding: 24px;
}
@media print {
  body {
    background: #fff;
  }
  .app-main {
    padding: 0;
  }
}
</style>
