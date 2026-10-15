<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { scalesApi } from '@/api/services'
import type { ScaleDefOut } from '@/types'

const scales = ref<ScaleDefOut[]>([])
const loading = ref(false)
const uploading = ref<Record<string, boolean>>({})

async function load() {
  loading.value = true
  try {
    const res = await scalesApi.list()
    scales.value = res.data
  } finally {
    loading.value = false
  }
}

async function onFileChange(e: Event, scale_id: string) {
  const target = e.target as HTMLInputElement
  if (!target.files || !target.files[0]) return
  const file = target.files[0]
  uploading.value[scale_id] = true
  try {
    const res = await scalesApi.reload(scale_id, file)
    ElMessage.success(`${res.data.scale_id} 已更新至 ${res.data.version}`)
    await load()
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || '替换失败')
  } finally {
    uploading.value[scale_id] = false
    target.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <h2 class="page-title">题目库管理</h2>
    <el-card shadow="never" v-loading="loading">
      <el-table :data="scales" border>
        <el-table-column prop="scale_id" label="量表 ID" />
        <el-table-column prop="version" label="版本" />
        <el-table-column prop="item_count" label="题目数" />
        <el-table-column prop="loaded_at" label="加载时间">
          <template #default="{ row }">
            {{ new Date(row.loaded_at).toLocaleString('zh-CN') }}
          </template>
        </el-table-column>
        <el-table-column label="替换上传">
          <template #default="{ row }">
            <input
              type="file"
              accept=".json"
              @change="onFileChange($event, row.scale_id)"
              :disabled="uploading[row.scale_id]"
            />
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="scales.length === 0" description="暂无题目库" />
    </el-card>
  </div>
</template>

<style scoped>
.page {
  max-width: 1000px;
  margin: 0 auto;
}
.page-title {
  margin-bottom: 20px;
}
</style>
