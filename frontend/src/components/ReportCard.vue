<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'
import type { ReportOut } from '@/types'

const props = defineProps<{ report: ReportOut; title?: string; subtitle?: string }>()
const chartRef = ref<HTMLDivElement | null>(null)
let chart: any = null

const dimensions = computed(() => {
  const scores = props.report.scores || {}
  const dims: { name: string; value: number }[] = []
  const sub = scores.subscales || {}
  for (const [k, v] of Object.entries(sub)) {
    const val = typeof v === 'object' && v !== null ? (v as any).score ?? 0 : Number(v) || 0
    dims.push({ name: k, value: Number(val.toFixed ? val.toFixed(2) : val) })
  }
  const fac = scores.factors || {}
  for (const [k, v] of Object.entries(fac)) {
    const val = typeof v === 'object' && v !== null ? (v as any).mean ?? (v as any).score ?? 0 : Number(v) || 0
    dims.push({ name: k, value: Number(val.toFixed ? val.toFixed(2) : val) })
  }
  return dims
})

const overall = computed(() => {
  const s = props.report.scores || {}
  const parts: string[] = []
  if (s.band) parts.push(`整体评级：${s.band}`)
  if (s.total_score !== undefined) parts.push(`总分：${s.total_score}`)
  if (s.total_mean !== undefined) parts.push(`总均分：${s.total_mean}`)
  if (s.validity_score !== undefined) parts.push(`效度分：${s.validity_score}`)
  return parts.join(' ｜ ') || '整体情况请见下方图表'
})

function initChart() {
  if (!chartRef.value) return
  if (chart) chart.dispose()
  chart = echarts.init(chartRef.value)
  const data = dimensions.value
  const maxVal = Math.max(1, ...data.map((d) => d.value))
  chart.setOption({
    tooltip: { trigger: 'item' },
    radar: {
      indicator: data.map((d) => ({ name: d.name, max: maxVal })),
      radius: '65%'
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            value: data.map((d) => d.value),
            name: '维度得分',
            areaStyle: { opacity: 0.2 },
            lineStyle: { color: '#3b82f6' },
            itemStyle: { color: '#3b82f6' }
          }
        ]
      }
    ]
  })
}

watch(dimensions, () => {
  if (chart) {
    const data = dimensions.value
    const maxVal = Math.max(1, ...data.map((d) => d.value))
    chart.setOption({
      radar: { indicator: data.map((d) => ({ name: d.name, max: maxVal })) },
      series: [{ data: [{ value: data.map((d) => d.value) }] }]
    })
  }
})

onMounted(() => {
  initChart()
  const handler = () => chart?.resize()
  window.addEventListener('resize', handler)
  onUnmounted(() => {
    window.removeEventListener('resize', handler)
    chart?.dispose()
  })
})

function print() {
  window.print()
}
</script>

<template>
  <div class="report-card">
    <div class="report-header">
      <div>
        <h2 class="report-title">{{ title || report.scale_name }}</h2>
        <p class="report-subtitle">{{ subtitle }}</p>
      </div>
      <el-button type="primary" plain @click="print" class="no-print">
        <el-icon><Printer /></el-icon> 打印报告
      </el-button>
    </div>

    <el-alert
      v-if="report.is_valid === false"
      title="本次作答效度量表提示异常，结果仅供参考，建议重新测评。"
      type="warning"
      :closable="false"
      show-icon
      class="no-print"
    />

    <div class="meta">
      <p><strong>量表：</strong>{{ report.scale_name }}</p>
      <p><strong>测评编号：</strong>{{ report.assessment_id }}</p>
      <p v-if="report.created_at">
        <strong>完成时间：</strong>{{ new Date(report.created_at).toLocaleString('zh-CN') }}
      </p>
      <p><strong>{{ overall }}</strong></p>
    </div>

    <div class="two-col">
      <div class="chart-wrap">
        <div ref="chartRef" class="chart"></div>
      </div>
      <div class="dim-table">
        <h3>维度得分</h3>
        <el-table :data="dimensions" border size="small" :header-cell-style="{ background: '#f3f4f6' }">
          <el-table-column prop="name" label="维度" />
          <el-table-column prop="value" label="得分" />
        </el-table>
      </div>
    </div>

    <div v-if="report.risk_flags && report.risk_flags.length" class="risk-box">
      <h3>关注提示</h3>
      <p v-for="(flag, idx) in report.risk_flags" :key="idx" class="risk-item">
        <el-tag :type="flag.severity === 'critical' ? 'danger' : flag.severity === 'high' ? 'warning' : 'info'" size="small">
          {{ flag.severity === 'critical' ? '严重' : flag.severity === 'high' ? '高度关注' : '提示' }}
        </el-tag>
        {{ flag.message }}
      </p>
    </div>

    <div v-if="report.llm_summary" class="summary">
      <h3>发展性反馈</h3>
      <p>{{ report.llm_summary }}</p>
    </div>

    <p class="print-footer">本系统结果属于发展性筛查参考，不构成医学诊断。</p>
  </div>
</template>

<style scoped>
.report-card {
  background: #fff;
  border-radius: 8px;
  padding: 24px;
  max-width: 960px;
  margin: 0 auto;
}
.report-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
  border-bottom: 1px solid #e5e7eb;
  padding-bottom: 12px;
}
.report-title {
  margin: 0;
  font-size: 22px;
}
.report-subtitle {
  margin: 4px 0 0;
  color: #6b7280;
  font-size: 14px;
}
.meta p {
  margin: 4px 0;
  color: #374151;
}
.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  margin: 20px 0;
}
.chart-wrap {
  min-height: 320px;
}
.chart {
  width: 100%;
  height: 320px;
}
.dim-table h3 {
  margin: 0 0 12px;
  font-size: 16px;
}
.risk-box,
.summary {
  margin-top: 20px;
  padding: 16px;
  border-radius: 6px;
  background: #f9fafb;
}
.risk-box h3,
.summary h3 {
  margin: 0 0 10px;
  font-size: 16px;
}
.risk-item {
  margin: 6px 0;
}
.summary p {
  line-height: 1.8;
  color: #374151;
}
.print-footer {
  display: none;
  margin-top: 20px;
  font-size: 12px;
  color: #6b7280;
  text-align: center;
}
@media print {
  .report-card {
    max-width: 100%;
    padding: 0;
    box-shadow: none;
  }
  .no-print {
    display: none !important;
  }
  .print-footer {
    display: block;
  }
  .two-col {
    grid-template-columns: 1fr 1fr;
    page-break-inside: avoid;
  }
  .chart {
    height: 260px;
  }
  .risk-box,
  .summary {
    page-break-inside: avoid;
  }
}
</style>
