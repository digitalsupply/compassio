import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { notifyApi } from '@/api/services'
import type { NotificationOut } from '@/types'

export const useNotifyStore = defineStore('notify', () => {
  const list = ref<NotificationOut[]>([])
  const unreadCount = ref(0)
  const lastCriticalIds = ref<number[]>([])

  const criticalUnread = computed(() =>
    list.value.filter((n) => n.severity === 'critical' && !n.read)
  )

  async function fetchList(unread?: boolean) {
    const res = await notifyApi.list(unread)
    list.value = res.data
    return res.data
  }

  async function fetchUnreadCount() {
    const res = await notifyApi.unreadCount()
    unreadCount.value = res.data.count
    return res.data.count
  }

  async function markRead(id: number) {
    await notifyApi.markRead(id)
    const item = list.value.find((n) => n.id === id)
    if (item) item.read = true
    await fetchUnreadCount()
  }

  async function poll() {
    await fetchUnreadCount()
    await fetchList(true)
  }

  function playBeep() {
    try {
      const AudioCtx = (window as any).AudioContext || (window as any).webkitAudioContext
      if (!AudioCtx) return
      const ctx = new AudioCtx()
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.connect(gain)
      gain.connect(ctx.destination)
      osc.type = 'sine'
      osc.frequency.value = 880
      gain.gain.setValueAtTime(0.1, ctx.currentTime)
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5)
      osc.start()
      osc.stop(ctx.currentTime + 0.5)
    } catch {
      // ignore
    }
  }

  async function pollAndAlert() {
    await poll()
    const newCritical = criticalUnread.value.filter(
      (n) => !lastCriticalIds.value.includes(n.id)
    )
    if (newCritical.length > 0) {
      playBeep()
    }
    lastCriticalIds.value = criticalUnread.value.map((n) => n.id)
  }

  return {
    list,
    unreadCount,
    criticalUnread,
    fetchList,
    fetchUnreadCount,
    markRead,
    poll,
    pollAndAlert,
    playBeep
  }
})
