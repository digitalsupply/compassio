<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { assessApi } from '@/api/services'
import type { ScaleBrief, ReportOut } from '@/types'

const router = useRouter()
const scales = ref<ScaleBrief[]>([])
const results = ref<ReportOut[]>([])
const loading = ref(false)
const currentAssess = ref<{ id: number; scale_id: string } | null>(null)

const completedResults = computed(() => results.value.filter((r) => r.status === 'completed'))

function loadCurrent() {
  try {
    const raw = localStorage.getItem('compassio_current_assessment')
    currentAssess.value = raw ? JSON.parse(raw) : null
  } catch {
    const id = Number(localStorage.getItem('compassio_current_assessment'))
    currentAssess.value = id ? { id, scale_id: '' } : null
  }
}

async function load() {
  loading.value = true
  try {
    const [s, r] = await Promise.all([
      assessApi.scales(),
      assessApi.myResults()
    ])
    scales.value = s.data
    results.value = r.data.results || []
  } finally {
    loading.value = false
  }
}

async function enterAssessment(scale_id: string, notice?: string) {
  try {
    const res = await assessApi.start(scale_id)
    const payload = { id: res.data.assessment_id, scale_id }
    localStorage.setItem('compassio_current_assessment', JSON.stringify(payload))
    if (notice) ElMessage.info(notice)
    router.push({
      path: `/student/assess/${res.data.assessment_id}`,
      query: { scale_id }
    })
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '开始测评失败')
  }
}

function start(scale: ScaleBrief) {
  // 1) 已完成该量表 → 直接提示，不进入作答
  if (scale.completed) {
    ElMessageBox.alert('同学，你已经完成测评，不需要重新测评！', '温馨提示', {
      confirmButtonText: '知道了',
      type: 'warning'
    }).catch(() => {})
    return
  }
  // 2) 该量表有进行中的测评 → 继续上次作答
  if (scale.in_progress) {
    enterAssessment(scale.scale_id, '继续上次作答')
    return
  }
  // 3) 已完成过其他量表 → 二次确认
  const completedOther = scales.value.find(
    (s) => s.scale_id !== scale.scale_id && s.completed
  )
  if (completedOther) {
    ElMessageBox.confirm(
      `同学，你已经完成〈${completedOther.name}〉测评，还要继续测评〈${scale.name}〉吗？`,
      '温馨提示',
      { confirmButtonText: '继续测评', cancelButtonText: '再想想', type: 'warning' }
    )
      .then(() => enterAssessment(scale.scale_id))
      .catch(() => {})
    return
  }
  enterAssessment(scale.scale_id)
}

function resume() {
  if (currentAssess.value) {
    const q = currentAssess.value.scale_id ? { scale_id: currentAssess.value.scale_id } : undefined
    router.push({ path: `/student/assess/${currentAssess.value.id}`, query: q })
  }
}

function responseTypeLabel(t?: string) {
  const m: Record<string, string> = { binary: '二选一作答', likert: '五级程度作答', choice: '多项选择作答' }
  return m[t || ''] || '逐题作答'
}

function viewReport(id: number) {
  router.push(`/student/reports?id=${id}`)
}

onMounted(() => {
  loadCurrent()
  load()
})
</script>

<template>
  <div class="page">
    <h2 class="page-title">学生首页</h2>

    <el-card class="section" shadow="never">
      <template #header>
        <span>可用量表</span>
      </template>
      <el-skeleton :rows="3" animated v-if="loading" />
      <div v-else class="scale-list">
        <div v-for="scale in scales" :key="scale.scale_id" class="scale-card">
          <div>
            <h3>
              {{ scale.name }}
              <el-tag v-if="scale.completed" type="success" size="small" class="tag">已完成</el-tag>
              <el-tag v-else-if="scale.in_progress" type="warning" size="small" class="tag">进行中</el-tag>
            </h3>
            <p class="desc">{{ scale.instruction }}</p>
            <p class="meta">共 {{ scale.item_count }} 题｜{{ responseTypeLabel(scale.response_type) }}</p>
          </div>
          <el-button type="primary" @click="start(scale)">
            {{ scale.in_progress ? '继续作答' : scale.completed ? '已测评' : '开始测评' }}
          </el-button>
        </div>
        <el-empty v-if="scales.length === 0" description="暂无可用量表" />
      </div>
    </el-card>

    <el-card class="section" shadow="never" v-if="currentAssess">
      <template #header>
        <span>断点续答</span>
      </template>
      <p>你有一场进行中的测评（编号 {{ currentAssess.id }}），可以继续完成。</p>
      <el-button type="warning" plain @click="resume">继续作答</el-button>
    </el-card>

    <el-card class="section" shadow="never">
      <template #header>
        <span>我的报告</span>
      </template>
      <el-table :data="completedResults" border>
        <el-table-column prop="scale_name" label="量表" />
        <el-table-column label="完成时间">
          <template #default="{ row }">
            {{ row.created_at ? new Date(row.created_at).toLocaleString('zh-CN') : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button link type="primary" @click="viewReport(row.assessment_id)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="completedResults.length === 0" description="暂无已完成报告" />
    </el-card>
  </div>
</template>

<style scoped>
.page {
  max-width: 900px;
  margin: 0 auto;
}
.page-title {
  margin-bottom: 20px;
}
.section {
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
.tag {
  margin-left: 8px;
  vertical-align: middle;
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
