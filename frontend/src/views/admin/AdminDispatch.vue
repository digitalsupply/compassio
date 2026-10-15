<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { reportApi } from '@/api/services'
import type { ClassReport } from '@/types'

const classes = ref<ClassReport[]>([])
const selectedClassId = ref<number | undefined>(undefined)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await reportApi.classes()
    classes.value = res.data
  } finally {
    loading.value = false
  }
}

async function dispatch() {
  if (!selectedClassId.value) {
    ElMessage.warning('请选择班级')
    return
  }
  try {
    const res = await reportApi.dispatch(selectedClassId.value)
    ElMessage.success(`已分发 ${res.data.dispatched} 份结果给班主任`)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '分发失败')
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <h2 class="page-title">分发结果</h2>
    <el-card shadow="never" v-loading="loading">
      <p class="hint">将已完成的班级学生结果分发给对应班主任，班主任可在“本班学生结果”中查看。</p>
      <div class="row">
        <el-select v-model="selectedClassId" placeholder="选择班级" clearable style="width: 300px">
          <el-option
            v-for="cls in classes"
            :key="cls.class_id"
            :label="cls.class_name"
            :value="cls.class_id"
          />
        </el-select>
        <el-button type="primary" @click="dispatch">确认分发</el-button>
      </div>
      <el-empty v-if="classes.length === 0" description="暂无班级" />
    </el-card>
  </div>
</template>

<style scoped>
.page {
  max-width: 800px;
  margin: 0 auto;
}
.page-title {
  margin-bottom: 20px;
}
.hint {
  color: #6b7280;
  font-size: 14px;
  margin-bottom: 16px;
}
.row {
  display: flex;
  gap: 12px;
  align-items: center;
}
</style>
