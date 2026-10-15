<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { usersApi } from '@/api/services'
import type { AccountOut } from '@/types'

const accounts = ref<AccountOut[]>([])
const filters = ref({ role: '', class_id: undefined as number | undefined, q: '' })
const loading = ref(false)
const resetResult = ref<{ username: string; temporary_password: string } | null>(null)
const resetDialogVisible = ref(false)

const roleOptions = [
  { label: '全部', value: '' },
  { label: '管理员', value: 'school_admin' },
  { label: '教师', value: 'teacher' },
  { label: '学生', value: 'student' }
]

const classOptions = computed(() => {
  const map = new Map<number, string>()
  accounts.value.forEach((u) => {
    if (u.class_id && u.class_name) map.set(u.class_id, u.class_name)
  })
  return [{ label: '全部班级', value: undefined }, ...Array.from(map).map(([id, name]) => ({ label: name, value: id }))]
})

async function load() {
  loading.value = true
  try {
    const res = await usersApi.accounts({
      role: filters.value.role || undefined,
      class: filters.value.class_id,
      q: filters.value.q || undefined
    })
    accounts.value = res.data
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

async function resetPassword(id: number) {
  try {
    const res = await usersApi.resetPassword(id)
    resetResult.value = res.data
    resetDialogVisible.value = true
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '重置失败')
  }
}

async function printRoster() {
  try {
    const res = await usersApi.printRoster({
      role: filters.value.role || undefined,
      class_id: filters.value.class_id
    })
    const w = window.open('', '_blank')
    if (w) {
      w.document.write(res.data)
      w.document.close()
      w.print()
    }
  } catch (e: any) {
    ElMessage.error('打印名单失败')
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <h2 class="page-title">账号管理</h2>

    <el-card shadow="never" class="section">
      <div class="filters">
        <el-select v-model="filters.role" placeholder="角色" clearable @change="load">
          <el-option
            v-for="opt in roleOptions"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
        <el-select v-model="filters.class_id" placeholder="班级" clearable @change="load">
          <el-option
            v-for="opt in classOptions"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
        <el-input v-model="filters.q" placeholder="搜索用户名/姓名/手机号" clearable @keyup.enter="load" />
        <el-button type="primary" @click="load">查询</el-button>
        <el-button plain @click="printRoster">打印名单</el-button>
      </div>

      <el-table :data="accounts" v-loading="loading" border class="account-table">
        <el-table-column prop="real_name" label="姓名" />
        <el-table-column prop="username" label="用户名" />
        <el-table-column prop="role" label="角色" />
        <el-table-column prop="class_name" label="班级" />
        <el-table-column label="是否班主任">
          <template #default="{ row }">
            <el-tag v-if="row.is_homeroom" type="success" size="small">班主任</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="phone" label="手机号" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button link type="primary" @click="resetPassword(row.id)">重置密码</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="resetDialogVisible" title="重置成功" width="360px" @closed="resetResult = null">
      <p v-if="resetResult">
        用户名：<strong>{{ resetResult.username }}</strong>
      </p>
      <p v-if="resetResult">
        临时密码：<strong>{{ resetResult.temporary_password }}</strong>
      </p>
      <p class="hint">首次登录需强制修改密码。</p>
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
.section {
  margin-bottom: 20px;
}
.filters {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.filters .el-input {
  width: 220px;
}
.account-table {
  margin-top: 8px;
}
.hint {
  color: #6b7280;
  font-size: 13px;
}
</style>
