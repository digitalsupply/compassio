<script setup lang="ts">
import { ref, onMounted, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { llmApi } from '@/api/services'
import type { LLMConfigOut, LLMConfigIn } from '@/types'

const presets = [
  { key: 'opencode-go', base_url: 'https://opencode.ai/inference/go/v1', model: 'deepseek-v4-flash' },
  { key: 'deepseek', base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
  { key: 'qwen', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus' },
  { key: 'zhipu', base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-flash' },
  { key: 'openrouter', base_url: 'https://openrouter.ai/api/v1', model: 'deepseek/deepseek-chat' },
  { key: 'volcano', base_url: 'https://ark.cn-volces.com/api/v3', model: '' },
  { key: 'kimi', base_url: 'https://api.moonshot.cn/v1', model: 'moonshot-v1-8k' },
  { key: 'ollama', base_url: 'http://host:11434/v1', model: '' },
  { key: 'custom', base_url: '', model: '' }
]

const configs = ref<LLMConfigOut[]>([])
const loading = ref(false)
const dialogVisible = ref(false)
const isEdit = ref(false)
const editId = ref<number | null>(null)
const extraHeadersText = ref('{}')
const form = reactive<LLMConfigIn>({
  name: '',
  provider_key: 'opencode-go',
  base_url: presets[0].base_url,
  api_key: '',
  model: presets[0].model,
  extra_headers: {},
  is_active: true,
  timeout_s: 30,
  is_default: false
})

function applyPreset(key: string) {
  const p = presets.find((x) => x.key === key)
  if (p) {
    form.base_url = p.base_url
    form.model = p.model
  }
}

function openCreate() {
  isEdit.value = false
  editId.value = null
  Object.assign(form, {
    name: '',
    provider_key: 'opencode-go',
    base_url: presets[0].base_url,
    api_key: '',
    model: presets[0].model,
    extra_headers: {},
    is_active: true,
    timeout_s: 30,
    is_default: false
  })
  extraHeadersText.value = '{}'
  dialogVisible.value = true
}

function openEdit(cfg: LLMConfigOut) {
  isEdit.value = true
  editId.value = cfg.id
  Object.assign(form, { ...cfg })
  // 后端出参是掩码，不能当作真实 key 回传：留空表示不修改（后端会保留原值）。
  form.api_key = ''
  extraHeadersText.value = JSON.stringify(cfg.extra_headers || {}, null, 2)
  dialogVisible.value = true
}

async function save() {
  try {
    form.extra_headers = JSON.parse(extraHeadersText.value || '{}')
  } catch {
    ElMessage.error('额外请求头 JSON 格式不正确')
    return
  }
  try {
    if (isEdit.value && editId.value) {
      await llmApi.update(editId.value, form)
      ElMessage.success('更新成功')
    } else {
      await llmApi.create(form)
      ElMessage.success('创建成功')
    }
    dialogVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  }
}

async function remove(id: number) {
  try {
    await llmApi.delete(id)
    ElMessage.success('删除成功')
    await load()
  } catch (e: any) {
    ElMessage.error('删除失败')
  }
}

async function test(id: number) {
  try {
    const res = await llmApi.test(id)
    ElMessage[res.data.ok ? 'success' : 'warning'](res.data.ok ? '连通成功' : '连通失败')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '测试失败')
  }
}

async function load() {
  loading.value = true
  try {
    const res = await llmApi.list()
    configs.value = res.data
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <h2 class="page-title">LLM 配置</h2>
    <el-card shadow="never" v-loading="loading">
      <div class="toolbar">
        <el-button type="primary" @click="openCreate">新增配置</el-button>
      </div>
      <el-table :data="configs" border>
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="provider_key" label="Provider" />
        <el-table-column prop="model" label="模型" />
        <el-table-column prop="base_url" label="Base URL" show-overflow-tooltip />
        <el-table-column prop="timeout_s" label="超时(s)" width="90" />
        <el-table-column label="默认" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.is_default" type="success" size="small">是</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="primary" @click="test(row.id)">测试</el-button>
            <el-button link type="danger" @click="remove(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="configs.length === 0" description="暂无 LLM 配置" />
    </el-card>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑配置' : '新增配置'" width="560px">
      <el-form :model="form" label-position="top">
        <el-form-item label="名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="Provider">
          <el-select v-model="form.provider_key" @change="applyPreset">
            <el-option v-for="p in presets" :key="p.key" :label="p.key" :value="p.key" />
          </el-select>
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="form.base_url" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="isEdit ? '留空则不修改（已设置）' : ''"
          />
        </el-form-item>
        <el-form-item label="模型">
          <el-input v-model="form.model" />
        </el-form-item>
        <el-form-item label="额外请求头（JSON）">
          <el-input v-model="extraHeadersText" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="超时（秒）">
          <el-input-number v-model="form.timeout_s" :min="1" :max="120" />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="form.is_active">启用</el-checkbox>
          <el-checkbox v-model="form.is_default">设为默认</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
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
  margin-bottom: 12px;
}
</style>
