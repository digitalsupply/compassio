<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { reportApi } from '@/api/services'
import type { ClassReport } from '@/types'

const reports = ref<ClassReport[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await reportApi.classes()
    reports.value = res.data
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

function riskSummary(risk_counts: Record<string, number>) {
  const parts: string[] = []
  if (risk_counts.critical) parts.push(`严重 ${risk_counts.critical}`)
  if (risk_counts.high) parts.push(`高度 ${risk_counts.high}`)
  if (risk_counts.info) parts.push(`提示 ${risk_counts.info}`)
  return parts.join(' ｜ ') || '暂无'
}

onMounted(load)
</script>

<template>
  <div class="page">
    <h2 class="page-title">班级报告</h2>
    <el-card shadow="never" v-loading="loading">
      <el-table :data="reports" border>
        <el-table-column prop="class_name" label="班级" />
        <el-table-column label="班主任">
          <template #default="{ row }">
            {{ row.head_teacher_name || '—' }}
          </template>
        </el-table-column>
        <el-table-column prop="grade_level" label="学段" />
        <el-table-column label="完成率">
          <template #default="{ row }">
            {{ row.completed_count }} / {{ row.student_count }}
            <el-progress :percentage="Math.round(row.completion_rate * 100)" />
          </template>
        </el-table-column>
        <el-table-column label="预警统计">
          <template #default="{ row }">
            {{ riskSummary(row.risk_counts) }}
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
</style>
