<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { assessApi } from '@/api/services'
import AssessRun from '@/components/AssessRun.vue'
import type { ScaleBrief } from '@/types'

const router = useRouter()
const scales = ref<ScaleBrief[]>([])
const loading = ref(false)
const sessionId = ref<number | null>(null)
const sessionOptions = ref<Array<{ value: number; label: string }>>([])

async function load() {
  loading.value = true
  try {
    const res = await assessApi.scales()
    scales.value = res.data
  } finally {
    loading.value = false
  }
}

async function start(scale: ScaleBrief) {
  try {
    const res = await assessApi.start(scale.scale_id)
    sessionId.value = res.data.assessment_id
    sessionOptions.value = scale.options
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '开始测评失败')
  }
}

function done() {
  router.push('/teacher/reports')
}

onMounted(load)
</script>

<template>
  <div class="page">
    <h2 class="page-title">我的测评</h2>

    <div v-if="!sessionId">
      <el-skeleton :rows="3" animated v-if="loading" />
      <div v-else class="scale-list">
        <div v-for="scale in scales" :key="scale.scale_id" class="scale-card">
          <div>
            <h3>{{ scale.name }}</h3>
            <p class="desc">{{ scale.instruction }}</p>
            <p class="meta">共 {{ scale.item_count }} 题｜{{ scale.response_type }}</p>
          </div>
          <el-button type="primary" @click="start(scale)">开始测评</el-button>
        </div>
        <el-empty v-if="scales.length === 0" description="暂无可用量表" />
      </div>
    </div>

    <AssessRun
      v-else
      :assessment-id="sessionId"
      :options="sessionOptions"
      :scale-name="scales.find((s) => s.options === sessionOptions)?.name"
      @done="done"
    />
  </div>
</template>

<style scoped>
.page {
  max-width: 720px;
  margin: 0 auto;
}
.page-title {
  margin-bottom: 20px;
}
.scale-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.scale-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fafafa;
}
.scale-card h3 {
  margin: 0 0 6px;
}
.desc {
  margin: 0 0 6px;
  color: #4b5563;
  font-size: 14px;
}
.meta {
  margin: 0;
  font-size: 13px;
  color: #9ca3af;
}
</style>
