<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { importApi } from '@/api/services'
import type { ImportPreview, ImportCommitResult } from '@/types'

const kind = ref<'teachers' | 'students'>('students')
const file = ref<File | null>(null)
const preview = ref<ImportPreview | null>(null)
const result = ref<ImportCommitResult | null>(null)
const loading = ref(false)

function onFileChange(e: Event) {
  const target = e.target as HTMLInputElement
  if (target.files && target.files[0]) {
    file.value = target.files[0]
    preview.value = null
    result.value = null
  }
}

async function downloadTemplate() {
  try {
    const res = await importApi.template(kind.value)
    const blob = new Blob([res.data], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${kind.value}_template.csv`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e: any) {
    ElMessage.error('下载模板失败')
  }
}

async function previewImport() {
  if (!file.value) {
    ElMessage.warning('请先选择文件')
    return
  }
  loading.value = true
  try {
    const res = await importApi.preview(kind.value, file.value)
    preview.value = res.data
    result.value = null
    if (res.data.errors.length) {
      ElMessage.warning(`发现 ${res.data.errors.length} 处错误，请修正后重新上传`)
    } else {
      ElMessage.success('校验通过，可提交导入')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '校验失败')
  } finally {
    loading.value = false
  }
}

async function commitImport() {
  if (!file.value) return
  loading.value = true
  try {
    const res = await importApi.commit(kind.value, file.value)
    result.value = res.data
    ElMessage.success(`成功导入 ${res.data.created} 个账号`)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '导入失败')
  } finally {
    loading.value = false
  }
}

function printRoster() {
  if (!result.value?.roster_html) return
  const w = window.open('', '_blank')
  if (w) {
    w.document.write(result.value.roster_html)
    w.document.close()
    w.print()
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">导入师生</h2>

    <el-card shadow="never" class="section">
      <template #header> 1. 下载模板 </template>
      <el-radio-group v-model="kind" class="kind-radio">
        <el-radio-button label="students">学生</el-radio-button>
        <el-radio-button label="teachers">教师</el-radio-button>
      </el-radio-group>
      <p class="hint">
        {{
          kind === 'students'
            ? '学生列：姓名,班级,性别,班主任（班级如：七年级(1)班）'
            : '教师列：姓名,手机号,性别,班级,是否班主任'
        }}
      </p>
      <el-button type="primary" plain @click="downloadTemplate">下载 {{ kind === 'students' ? '学生' : '教师' }} 模板</el-button>
    </el-card>

    <el-card shadow="never" class="section">
      <template #header> 2. 上传并校验 </template>
      <input type="file" accept=".csv,.xlsx" @change="onFileChange" />
      <el-button type="primary" :loading="loading" @click="previewImport" class="ml">校验</el-button>

      <div v-if="preview" class="preview">
        <p>共 {{ preview.total_rows }} 行，解析出 {{ preview.accounts.length }} 条账号。</p>
        <el-alert
          v-for="(w, idx) in preview.warnings"
          :key="`w-${idx}`"
          :title="w"
          type="warning"
          :closable="false"
          show-icon
          class="alert-row"
        />
        <el-alert
          v-for="err in preview.errors"
          :key="err.row"
          :title="`第 ${err.row} 行：${err.message}`"
          type="error"
          :closable="false"
          show-icon
          class="alert-row"
        />
        <el-table :data="preview.accounts" border size="small" class="preview-table">
          <el-table-column prop="row" label="行号" width="70" />
          <el-table-column prop="real_name" label="姓名" />
          <el-table-column prop="base_username" label="拟用用户名" />
          <el-table-column prop="class_name" label="班级" />
          <el-table-column v-if="kind === 'teachers'" label="是否班主任">
            <template #default="{ row }">{{ row.is_homeroom ? '是' : '否' }}</template>
          </el-table-column>
        </el-table>
        <el-button
          v-if="preview.errors.length === 0"
          type="success"
          :loading="loading"
          @click="commitImport"
          class="commit-btn"
        >
          确认导入并生成账号
        </el-button>
      </div>
    </el-card>

    <el-card shadow="never" class="section" v-if="result">
      <template #header> 3. 导入结果 </template>
      <p>成功创建 {{ result.created }} 个账号。</p>
      <el-button type="primary" @click="printRoster">打印账号名单</el-button>
      <div v-html="result.roster_html" class="roster-preview"></div>
    </el-card>
  </div>
</template>

<style scoped>
.page {
  max-width: 960px;
  margin: 0 auto;
}
.page-title {
  margin-bottom: 20px;
}
.section {
  margin-bottom: 20px;
}
.kind-radio {
  margin-bottom: 12px;
}
.hint {
  color: #6b7280;
  font-size: 14px;
  margin: 0 0 12px;
}
.ml {
  margin-left: 12px;
}
.preview {
  margin-top: 16px;
}
.alert-row {
  margin-bottom: 8px;
}
.preview-table {
  margin-top: 12px;
}
.commit-btn {
  margin-top: 12px;
}
.roster-preview {
  margin-top: 16px;
  overflow-x: auto;
}
</style>
