<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { notifyApi } from '@/api/services'
import { useNotifyStore } from '@/stores/notify'
import type { NotificationOut } from '@/types'

const list = ref<NotificationOut[]>([])
const unreadOnly = ref(false)
const loading = ref(false)
const notifyStore = useNotifyStore()

async function load() {
  loading.value = true
  try {
    const res = await notifyApi.list(unreadOnly.value || undefined)
    list.value = res.data
  } finally {
    loading.value = false
  }
}

async function markRead(id: number) {
  try {
    await notifyApi.markRead(id)
    ElMessage.success('已标记为已读')
    await load()
    await notifyStore.fetchUnreadCount()
  } catch (e: any) {
    ElMessage.error('操作失败')
  }
}

function severityType(s: string) {
  if (s === 'critical') return 'danger'
  if (s === 'high') return 'warning'
  return 'info'
}

function severityLabel(s: string) {
  if (s === 'critical') return '严重'
  if (s === 'high') return '高度'
  return '一般'
}

onMounted(load)
</script>

<template>
  <div class="page">
    <h2 class="page-title">
      通知中心
      <el-badge :value="notifyStore.unreadCount" v-if="notifyStore.unreadCount > 0" />
    </h2>

    <el-card shadow="never">
      <div class="toolbar">
        <el-radio-group v-model="unreadOnly" @change="load">
          <el-radio-button :label="false">全部</el-radio-button>
          <el-radio-button :label="true">未读</el-radio-button>
        </el-radio-group>
        <el-button plain @click="load">刷新</el-button>
      </div>

      <el-timeline>
        <el-timeline-item
          v-for="n in list"
          :key="n.id"
          :type="severityType(n.severity)"
          :timestamp="new Date(n.created_at).toLocaleString('zh-CN')"
        >
          <div class="notify-card" :class="{ unread: !n.read }">
            <div class="notify-head">
              <el-tag :type="severityType(n.severity)" size="small">{{ severityLabel(n.severity) }}</el-tag>
              <h4>{{ n.title }}</h4>
            </div>
            <p>{{ n.body }}</p>
            <el-button v-if="!n.read" link type="primary" @click="markRead(n.id)">标记已读</el-button>
          </div>
        </el-timeline-item>
      </el-timeline>

      <el-empty v-if="list.length === 0" description="暂无通知" />
    </el-card>
  </div>
</template>

<style scoped>
.page {
  max-width: 900px;
  margin: 0 auto;
}
.page-title {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.notify-card {
  background: #f9fafb;
  padding: 12px 16px;
  border-radius: 6px;
}
.notify-card.unread {
  background: #eff6ff;
  border-left: 4px solid #3b82f6;
}
.notify-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.notify-head h4 {
  margin: 0;
}
.notify-card p {
  margin: 6px 0;
  color: #374151;
}
</style>
