<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { assessApi } from '@/api/services'
import type { NextItem, ScaleBrief } from '@/types'

const props = defineProps<{ id: string }>()
const router = useRouter()
const route = useRoute()

const assessmentId = Number(props.id)
const current = ref<NextItem | null>(null)
const scales = ref<ScaleBrief[]>([])
const loading = ref(false)
const transitionVisible = ref(false)
const scaleId = computed(() => (route.query.scale_id as string) || '')

const progressPct = computed(() => {
  if (!current.value) return 0
  const { answered, total } = current.value.progress
  return total ? Math.round((answered / total) * 100) : 0
})

const scaleInfo = computed(() =>
  scales.value.find((s) => s.scale_id === scaleId.value)
)

async function loadScales() {
  try {
    const res = await assessApi.scales()
    scales.value = res.data
  } catch {
    // ignore
  }
}

async function fetchNext() {
  loading.value = true
  try {
    const res = await assessApi.next(assessmentId)
    current.value = res.data
    if (res.data.transition) {
      transitionVisible.value = true
      setTimeout(() => (transitionVisible.value = false), 2500)
    }
    if (res.data.finished) {
      await finish()
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载题目失败')
  } finally {
    loading.value = false
  }
}

async function answer(value: number) {
  if (!current.value?.item_id) return
  loading.value = true
  try {
    await assessApi.answer(assessmentId, current.value.item_id, value)
    await fetchNext()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '提交失败')
  } finally {
    loading.value = false
  }
}

async function finish() {
  try {
    await assessApi.finish(assessmentId)
    localStorage.removeItem('compassio_current_assessment')
    ElMessageBox.alert('测评已完成，去看看属于你的发展性反馈吧。', '完成', {
      confirmButtonText: '查看报告',
      callback: () => router.replace('/student/reports')
    })
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '结束失败')
  }
}

onMounted(() => {
  loadScales()
  fetchNext()
})
</script>

<template>
  <div class="page">
    <el-card class="assess-card" shadow="never" v-loading="loading">
      <div class="progress-row">
        <span>进度</span>
        <el-progress :percentage="progressPct" class="progress" />
        <span>{{ current?.progress.answered || 0 }} / {{ current?.progress.total || 0 }}</span>
      </div>

      <transition name="bubble">
        <div v-if="transitionVisible && current?.transition" class="llm-bubble">
          {{ current.transition }}
        </div>
      </transition>

      <div v-if="current?.text" class="question">
        <p class="q-text">{{ current.text }}</p>
      </div>

      <div v-if="scaleInfo" class="options">
        <el-button
          v-for="opt in scaleInfo.options"
          :key="opt.value"
          size="large"
          class="opt-btn"
          @click="answer(opt.value)"
        >
          {{ opt.label }}
        </el-button>
      </div>

      <el-empty v-if="!current && !loading" description="暂无题目" />
    </el-card>
  </div>
</template>

<style scoped>
.page {
  max-width: 720px;
  margin: 0 auto;
}
.assess-card {
  padding: 12px;
}
.progress-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
  font-size: 14px;
  color: #6b7280;
}
.progress {
  flex: 1;
}
.llm-bubble {
  background: #eff6ff;
  color: #1e40af;
  padding: 14px 18px;
  border-radius: 18px;
  border-bottom-left-radius: 4px;
  margin-bottom: 20px;
  font-size: 14px;
  max-width: 80%;
}
.bubble-enter-active,
.bubble-leave-active {
  transition: all 0.4s ease;
}
.bubble-enter-from,
.bubble-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
.question {
  background: #f9fafb;
  padding: 24px;
  border-radius: 8px;
  margin-bottom: 24px;
  min-height: 120px;
  display: flex;
  align-items: center;
}
.q-text {
  font-size: 18px;
  line-height: 1.6;
  margin: 0;
}
.options {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 12px;
}
.opt-btn {
  justify-content: center;
}
</style>
