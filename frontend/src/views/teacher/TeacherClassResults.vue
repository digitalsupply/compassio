<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { teacherApi, downloadResponse } from '@/api/services'
import ReportCard from '@/components/ReportCard.vue'
import type { TeacherClassResultOut, TeacherClassSummary } from '@/types'

const reports = ref<TeacherClassResultOut[]>([])
const selected = ref<TeacherClassResultOut | null>(null)
const summary = ref<TeacherClassSummary | null>(null)
const loading = ref(false)
const exporting = ref(false)
const permissionError = ref('')
const scaleId = ref<'mht' | 'mssmhs'>('mht')
const exportFormat = ref<'xlsx' | 'csv'>('xlsx')
const keyword = ref('')
const lastUpdated = ref<Date | null>(null)

// 当前统计与导出口径：同一选择器同时驱动汇总、列表与导出文件。
const scopeText = computed(
  () =>
    `当前统计与导出：${scaleId.value === 'mht' ? 'MHT（心理健康诊断测验）' : 'MSSMHS（中学生心理健康量表）'}`
)

const filteredReports = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return reports.value
  return reports.value.filter((r) =>
    [r.student_name, r.username, r.class_name, r.scale_name]
      .filter(Boolean)
      .some((v) => String(v).toLowerCase().includes(kw))
  )
})

async function load() {
  loading.value = true
  permissionError.value = ''
  try {
    const [sum, list] = await Promise.all([
      teacherApi.classSummary(scaleId.value),
      teacherApi.classResults(scaleId.value)
    ])
    summary.value = sum.data
    reports.value = list.data || []
    selected.value = reports.value[0] || null
    lastUpdated.value = new Date()
  } catch (e: any) {
    const status = e.response?.status
    if (status === 403) {
      permissionError.value = e.response?.data?.detail || '你当前不是班主任，无法查看本班学生结果'
    } else {
      ElMessage.error(e.response?.data?.detail || '加载班级结果失败')
    }
  } finally {
    loading.value = false
  }
}

function refresh() {
  load()
}

async function doExport() {
  exporting.value = true
  try {
    const res = await teacherApi.classExport(scaleId.value, exportFormat.value)
    const name = summary.value?.class_name || '本班'
    downloadResponse(res as any, `${name}_${scaleId.value}_测评结果.${exportFormat.value}`)
    ElMessage.success('导出成功')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '导出失败')
  } finally {
    exporting.value = false
  }
}

function exportClass() {
  const pending = summary.value?.pending ?? 0
  const completed = summary.value?.completed ?? 0
  const total = summary.value?.total ?? 0
  const name = summary.value?.class_name || '本班'
  const scaleShort = scaleId.value === 'mht' ? 'MHT' : 'MSSMHS'
  let message: string
  if (completed === 0) {
    message = `${name}（${scaleShort}）目前还没有同学完成测评，导出的文件将只包含未完成名单，是否继续？`
  } else if (pending > 0) {
    message = `${name}还有 ${pending} 位同学未完成测评，是否导出？`
  } else {
    message = `${name}（${scaleShort}）已全部完成，共 ${total} 人，确认导出？`
  }
  ElMessageBox.confirm(message, '导出提醒', {
    confirmButtonText: completed === 0 ? '继续导出' : '仍要导出',
    cancelButtonText: '取消',
    type: 'warning'
  })
    .then(doExport)
    .catch(() => {})
}

function scoreText(row: TeacherClassResultOut): string {
  const s = row.scores || {}
  if (row.scale_id === 'mht') {
    return s.total_score !== undefined && s.total_score !== null ? String(s.total_score) : '—'
  }
  return s.total_mean !== undefined && s.total_mean !== null ? String(s.total_mean) : '—'
}

function validityText(row: TeacherClassResultOut): string {
  if (row.is_valid === false) return '无效'
  return '有效'
}

function riskLevel(row: TeacherClassResultOut): { type: string; label: string } {
  const rank: Record<string, number> = { critical: 3, high: 2, info: 1 }
  const label: Record<string, string> = { critical: '严重', high: '高度关注', info: '提示' }
  let best = ''
  for (const flag of row.risk_flags || []) {
    const sev = String((flag as any).severity || '')
    if (!best || (rank[sev] || 0) > (rank[best] || 0)) best = sev
  }
  if (!best) return { type: 'info', label: '无' }
  return { type: best === 'critical' ? 'danger' : best === 'high' ? 'warning' : 'info', label: label[best] || best }
}

function fmtTime(value: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString('zh-CN')
}

function viewReport(row: TeacherClassResultOut) {
  selected.value = row
  nextTick(() => {
    document.querySelector('.report-detail')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}

function printReport(row: TeacherClassResultOut) {
  selected.value = row
  nextTick(() => window.print())
}

function fmtUpdated(value: Date | null): string {
  return value ? value.toLocaleTimeString('zh-CN') : '—'
}

watch(scaleId, load)

onMounted(load)
</script>

<template>
  <div class="page" v-loading="loading">
    <h2 class="page-title">本班学生结果</h2>

    <el-alert
      v-if="permissionError"
      :title="permissionError"
      type="warning"
      :closable="false"
      show-icon
    />

    <template v-else>
      <p class="hint">学生答完即自动出现在这里，无需等待管理员分发。仅显示你担任班主任的班级的学生测评结果。</p>

      <el-card class="summary" shadow="never">
        <div class="summary-row">
          <div class="summary-item">
            <span class="s-label">班级</span>
            <span class="s-value">{{ summary?.class_name || '—' }}</span>
          </div>
          <div class="summary-item">
            <span class="s-label">应测人数</span>
            <span class="s-value">{{ summary?.total ?? 0 }}</span>
          </div>
          <div class="summary-item">
            <span class="s-label">已完成</span>
            <span class="s-value">{{ summary?.completed ?? 0 }}</span>
          </div>
          <div class="summary-item">
            <span class="s-label">未完成</span>
            <span class="s-value pending">{{ summary?.pending ?? 0 }}</span>
          </div>
          <div class="summary-item">
            <span class="s-label">完成率</span>
            <span class="s-value">{{ Math.round((summary?.completion_rate || 0) * 100) }}%</span>
          </div>
        </div>
        <div class="toolbar">
          <span>统计与导出量表：</span>
          <el-select v-model="scaleId" style="width: 220px">
            <el-option label="MHT 心理健康诊断测验" value="mht" />
            <el-option label="MSSMHS 中学生心理健康量表" value="mssmhs" />
          </el-select>
          <el-input
            v-model="keyword"
            placeholder="按姓名 / 用户名搜索"
            clearable
            style="width: 200px"
          />
          <el-select v-model="exportFormat" style="width: 110px">
            <el-option label="Excel" value="xlsx" />
            <el-option label="CSV" value="csv" />
          </el-select>
          <el-button :loading="loading" @click="refresh">刷新</el-button>
          <el-button type="primary" :loading="exporting" @click="exportClass">导出</el-button>
          <span class="updated">最后更新：{{ fmtUpdated(lastUpdated) }}</span>
        </div>
      </el-card>

      <p class="scope-hint">
        {{ scopeText }}　｜　已完成 {{ summary?.completed ?? 0 }} 人 / 应测 {{ summary?.total ?? 0 }} 人，
        与下方列表、导出文件同一口径。
      </p>

      <el-card shadow="never" class="table-card">
        <el-table :data="filteredReports" border>
          <el-table-column prop="student_name" label="学生姓名" min-width="100" />
          <el-table-column prop="class_name" label="班级" min-width="110" />
          <el-table-column prop="gender" label="性别" width="70" />
          <el-table-column prop="scale_name" label="量表" min-width="180" />
          <el-table-column label="第几次" width="80">
            <template #default="{ row }">{{ row.attempt_no ?? '—' }}</template>
          </el-table-column>
          <el-table-column label="有效性" width="90">
            <template #default="{ row }">
              <el-tag :type="row.is_valid === false ? 'danger' : 'success'" size="small">
                {{ validityText(row) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="总分（MHT）/总均分（MSSMHS）" width="200">
            <template #default="{ row }">{{ scoreText(row) }}</template>
          </el-table-column>
          <el-table-column label="预警级别" width="110">
            <template #default="{ row }">
              <el-tag :type="riskLevel(row).type" size="small">{{ riskLevel(row).label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="完成时间" min-width="170">
            <template #default="{ row }">{{ fmtTime(row.completed_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button type="primary" link @click="viewReport(row)">查看报告</el-button>
              <el-button link @click="printReport(row)">打印</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="filteredReports.length === 0" description="本班暂无已完成的测评结果" />
      </el-card>

      <section class="report-detail" v-if="selected">
        <ReportCard
          :report="selected"
          :subtitle="`${selected.student_name} ｜ ${selected.class_name} ｜ 第 ${selected.attempt_no ?? 1} 次`"
        />
      </section>
    </template>
  </div>
</template>

<style scoped>
.page {
  max-width: 1280px;
  margin: 0 auto;
}
.page-title {
  margin-bottom: 8px;
}
.hint {
  color: #6b7280;
  font-size: 14px;
  margin-bottom: 16px;
}
.summary {
  margin-bottom: 20px;
}
.summary-row {
  display: flex;
  gap: 32px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.summary-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.s-label {
  font-size: 12px;
  color: #9ca3af;
}
.s-value {
  font-size: 20px;
  font-weight: 600;
  color: #1f2937;
}
.s-value.pending {
  color: #d97706;
}
.toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}
.updated {
  font-size: 12px;
  color: #9ca3af;
  margin-left: auto;
}
.scope-hint {
  margin: 0 0 16px;
  font-size: 14px;
  font-weight: 600;
  color: #2563eb;
}
.table-card {
  margin-bottom: 20px;
}
.report-detail {
  min-width: 0;
}
@media print {
  .hint,
  .summary,
  .table-card {
    display: none !important;
  }
  .report-detail {
    display: block;
  }
}
</style>
