<script setup lang="ts">
import { ref, computed, onMounted, onErrorCaptured, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { assessApi } from '@/api/services'
import ReportCard from '@/components/ReportCard.vue'
import type { ReportOut, StudentBrief } from '@/types'

const route = useRoute()
const router = useRouter()
const reports = ref<ReportOut[]>([])
const student = ref<StudentBrief | null>(null)
const selected = ref<ReportOut | null>(null)
const loading = ref(false)
// 组件级异常兜底：任何子组件渲染异常都显示友好文案而不是白屏。
const renderError = ref(false)

const studentLine = computed(() => {
  const s = student.value
  if (!s) return ''
  return [s.real_name, s.class_name, s.gender, `用户名：${s.username}`].filter(Boolean).join(' · ')
})

const EMPTY_TEXT = '还没有完成的测评，去首页选一个量表开始吧'

function timeOf(report: ReportOut): number {
  if (!report.created_at) return 0
  const t = Date.parse(report.created_at)
  return Number.isNaN(t) ? 0 : t
}

const sortedReports = computed(() =>
  [...reports.value].sort((a, b) => timeOf(b) - timeOf(a))
)
const completedReports = computed(() =>
  sortedReports.value.filter((r) => r.status === 'completed')
)

function attemptLabel(report: ReportOut): string {
  const when = report.created_at
    ? new Date(report.created_at).toLocaleString('zh-CN')
    : ''
  if (report.status !== 'completed') {
    return `进行中${report.attempt_no ? ` · 第 ${report.attempt_no} 次` : ''}`
  }
  const nth = report.attempt_no ? `第 ${report.attempt_no} 次测评` : '测评'
  return when ? `${nth} · ${when}` : nth
}

async function load() {
  loading.value = true
  renderError.value = false
  try {
    const res = await assessApi.myResults()
    reports.value = res.data.results || []
    student.value = res.data.student || null
    pickFromQuery()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载报告失败')
  } finally {
    loading.value = false
  }
}

function pickFromQuery() {
  const id = Number(route.query.id)
  if (id) {
    const found = sortedReports.value.find((r) => r.assessment_id === id)
    if (found) {
      selected.value = found
      return
    }
  }
  // 默认选中最近一次已完成；一条都没有则显示空状态。
  selected.value = completedReports.value[0] || null
}

function select(report: ReportOut) {
  if (report.status !== 'completed') {
    // 进行中的测评：点击继续作答
    router.push({
      path: `/student/assess/${report.assessment_id}`,
      query: report.scale_id ? { scale_id: report.scale_id } : undefined
    })
    return
  }
  selected.value = report
  router.replace({ query: { id: report.assessment_id } })
}

watch(() => route.query.id, pickFromQuery)

onErrorCaptured((err) => {
  console.error('report render error', err)
  renderError.value = true
  return false
})

onMounted(load)
</script>

<template>
  <div class="page" v-loading="loading">
    <h2 class="page-title">我的报告</h2>

    <div v-if="renderError" class="render-error">
      <el-result icon="error" title="报告加载异常，请稍后重试">
        <template #extra>
          <el-button type="primary" @click="load">重新加载</el-button>
        </template>
      </el-result>
    </div>

    <div v-else class="layout">
      <aside class="report-list">
        <el-card shadow="never">
          <div
            v-for="report in sortedReports"
            :key="report.assessment_id"
            class="report-item"
            :class="{ active: selected?.assessment_id === report.assessment_id }"
            @click="select(report)"
          >
            <p class="r-name">
              {{ report.scale_name }}
              <el-tag v-if="report.status !== 'completed'" type="warning" size="small">进行中</el-tag>
            </p>
            <p class="r-date">{{ attemptLabel(report) }}</p>
          </div>
          <el-empty v-if="reports.length === 0" :description="EMPTY_TEXT" />
        </el-card>
      </aside>

      <section class="report-detail" v-if="selected">
        <div class="stu-info" v-if="studentLine">
          <span class="stu-label">学生信息</span>
          <span class="stu-line">{{ studentLine }}</span>
        </div>
        <ReportCard :report="selected" :subtitle="attemptLabel(selected)" />
      </section>
      <section class="report-detail" v-else>
        <div class="stu-info" v-if="studentLine">
          <span class="stu-label">学生信息</span>
          <span class="stu-line">{{ studentLine }}</span>
        </div>
        <el-empty :description="EMPTY_TEXT" />
      </section>
    </div>
  </div>
</template>

<style scoped>
.page {
  max-width: 1200px;
  margin: 0 auto;
}
.page-title {
  margin-bottom: 20px;
}
.render-error {
  background: #fff;
  border-radius: 8px;
  padding: 24px;
}
.layout {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 20px;
}
.report-list {
  align-self: start;
}
.report-item {
  padding: 12px;
  border-bottom: 1px solid #f3f4f6;
  cursor: pointer;
  border-radius: 6px;
}
.report-item:hover,
.report-item.active {
  background: #eff6ff;
}
.r-name {
  margin: 0;
  font-weight: 600;
}
.r-date {
  margin: 4px 0 0;
  font-size: 12px;
  color: #9ca3af;
}
.stu-info {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding: 10px 14px;
  border-radius: 8px;
  background: #f5f7fb;
  border: 1px solid #e4e8f0;
}
.stu-label {
  font-weight: 600;
  color: #4a5878;
  flex: none;
}
.stu-line {
  color: #303133;
}
.report-detail {
  min-width: 0;
}
@media print {
  .report-list {
    display: none;
  }
  .layout {
    display: block;
  }
}
</style>
