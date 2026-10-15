<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { reportApi, downloadResponse } from '@/api/services'
import type { ClassReport } from '@/types'

type StatScale = 'all' | 'mht' | 'mssmhs'

const reports = ref<ClassReport[]>([])
const loading = ref(false)
// 「统计与导出量表」：同一口径同时驱动表格统计与导出文件。
const statScale = ref<StatScale>('all')
const exportFormat = ref<'xlsx' | 'csv'>('xlsx')
const exportingId = ref<number | null>(null)

const SCALE_TEXT: Record<StatScale, string> = {
  all: '全部量表（MHT + MSSMHS 合并统计）',
  mht: 'MHT（心理健康诊断测验）',
  mssmhs: 'MSSMHS（中学生心理健康量表）'
}

// 当前统计与导出口径（页面显式标出）。
const scopeText = computed(() => `当前统计与导出：${SCALE_TEXT[statScale.value]}`)

// 导出文件名/提示里的短量表名（选「全部量表」时禁止导出，无此值）。
const exportScaleShort = computed(() => (statScale.value === 'mht' ? 'MHT' : 'MSSMHS'))
const exportDisabled = computed(() => statScale.value === 'all')

async function load() {
  loading.value = true
  try {
    const res = await reportApi.classes(statScale.value)
    reports.value = res.data
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

// 切换口径即重新拉取班级数据，保证「完成 x / 总数」「完成率」「未完成」与导出同一口径。
watch(statScale, load)

function riskSummary(risk_counts: Record<string, number>) {
  const parts: string[] = []
  if (risk_counts.critical) parts.push(`严重 ${risk_counts.critical}`)
  if (risk_counts.high) parts.push(`高度 ${risk_counts.high}`)
  if (risk_counts.info) parts.push(`提示 ${risk_counts.info}`)
  return parts.join(' ｜ ') || '暂无'
}

function pendingOf(row: ClassReport): number {
  if (typeof row.pending === 'number') return row.pending
  return Math.max((row.total ?? row.student_count) - (row.completed ?? row.completed_count), 0)
}

async function doExport(row: ClassReport) {
  exportingId.value = row.class_id
  const scale = statScale.value === 'all' ? 'mht' : statScale.value
  try {
    const res = await reportApi.exportClass(row.class_id, scale, exportFormat.value)
    downloadResponse(
      res as any,
      `${row.class_name}_${scale}_测评结果.${exportFormat.value}`
    )
    ElMessage.success('导出成功')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '导出失败')
  } finally {
    exportingId.value = null
  }
}

async function exportClass(row: ClassReport) {
  if (exportDisabled.value) return
  const completed = row.completed_count
  const pending = pendingOf(row)
  const total = row.student_count
  let message: string
  if (completed === 0) {
    // 该量表 0 人完成：导出文件只含未完成名单。
    message = `${row.class_name}（${exportScaleShort.value}）目前还没有同学完成测评，导出的文件将只包含未完成名单，是否继续？`
  } else if (pending > 0) {
    message = `${row.class_name}还有 ${pending} 位同学未完成测评，是否导出？`
  } else {
    message = `${row.class_name}（${exportScaleShort.value}）已全部完成，共 ${total} 人，确认导出？`
  }
  ElMessageBox.confirm(message, '导出提醒', {
    confirmButtonText: completed === 0 ? '继续导出' : '仍要导出',
    cancelButtonText: '取消',
    type: 'warning'
  })
    .then(() => doExport(row))
    .catch(() => {})
}

onMounted(load)
function gradeLabel(g?: string) {
  const m: Record<string, string> = { primary: '小学', junior: '初中', senior: '高中' }
  return m[g || ''] || (g || '-')
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">班级报告</h2>
    <el-card shadow="never" v-loading="loading">
      <div class="toolbar">
        <span>统计与导出量表：</span>
        <el-select v-model="statScale" style="width: 260px">
          <el-option label="全部量表（合并统计）" value="all" />
          <el-option label="MHT 心理健康诊断测验" value="mht" />
          <el-option label="MSSMHS 中学生心理健康量表" value="mssmhs" />
        </el-select>
        <span>格式：</span>
        <el-select v-model="exportFormat" style="width: 110px">
          <el-option label="Excel" value="xlsx" />
          <el-option label="CSV" value="csv" />
        </el-select>
      </div>
      <p class="scope-hint">{{ scopeText }}</p>
      <el-alert
        v-if="exportDisabled"
        type="info"
        :closable="false"
        show-icon
        title="导出请先选择具体量表（MHT 或 MSSMHS）"
        class="scope-alert"
      />
      <el-table :data="reports" border>
        <el-table-column prop="class_name" label="班级" />
        <el-table-column label="班主任">
          <template #default="{ row }">
            {{ row.head_teacher_name || '—' }}
          </template>
        </el-table-column>
        <el-table-column prop="grade_level" label="学段">
        <template #default="{ row }">{{ gradeLabel(row.grade_level) }}</template>
      </el-table-column>
        <el-table-column label="完成率">
          <template #default="{ row }">
            {{ row.completed_count }} / {{ row.student_count }}
            <el-progress :percentage="Math.round(row.completion_rate * 100)" />
          </template>
        </el-table-column>
        <el-table-column label="未完成">
          <template #default="{ row }">
            <el-tag :type="pendingOf(row) > 0 ? 'warning' : 'success'" size="small">
              {{ pendingOf(row) }} 人
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="预警统计">
          <template #default="{ row }">
            {{ riskSummary(row.risk_counts) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110">
          <template #default="{ row }">
            <el-tooltip
              content="导出请先选择具体量表"
              placement="top"
              :disabled="!exportDisabled"
            >
              <span>
                <el-button
                  type="primary"
                  link
                  :disabled="exportDisabled"
                  :loading="exportingId === row.class_id"
                  @click="exportClass(row)"
                >
                  导出
                </el-button>
              </span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column type="expand" label="维度均值">
          <template #default="{ row }">
            <el-descriptions border :column="3" size="small">
              <el-descriptions-item
                v-for="(val, key) in row.dimension_means"
                :key="key"
                :label="key"
              >
                {{ val }}
              </el-descriptions-item>
            </el-descriptions>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="reports.length === 0" description="暂无班级数据" />
    </el-card>
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
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.scope-hint {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 600;
  color: #2563eb;
}
.scope-alert {
  margin-bottom: 12px;
}
</style>
