<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { assessApi } from '@/api/services'
import ReportCard from '@/components/ReportCard.vue'
import type { ReportOut } from '@/types'

const reports = ref<ReportOut[]>([])
const selected = ref<ReportOut | null>(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await assessApi.myResults()
    reports.value = (res.data.results || []).filter((r) => r.status === 'completed')
    selected.value = reports.value[0] || null
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载报告失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page" v-loading="loading">
    <h2 class="page-title">我的报告</h2>
    <div class="layout">
      <aside class="report-list">
        <el-card shadow="never">
          <div
            v-for="report in reports"
            :key="report.assessment_id"
            class="report-item"
            :class="{ active: selected?.assessment_id === report.assessment_id }"
            @click="selected = report"
          >
            <p class="r-name">{{ report.scale_name }}</p>
            <p class="r-date">
              {{ report.created_at ? new Date(report.created_at).toLocaleDateString('zh-CN') : '-' }}
            </p>
          </div>
          <el-empty v-if="reports.length === 0" description="暂无报告" />
        </el-card>
      </aside>
      <section class="report-detail" v-if="selected">
        <ReportCard :report="selected" />
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
