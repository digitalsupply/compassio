<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { usersApi } from '@/api/services'
import type { AccountOut, ClassOut } from '@/types'

const accounts = ref<AccountOut[]>([])
const classes = ref<ClassOut[]>([])
const filters = ref({ role: '', class_id: undefined as number | undefined, q: '' })
const loading = ref(false)

// 选中行（批量删除用）
const selection = ref<AccountOut[]>([])
const tableRef = ref()

// 凭证弹窗：重置密码 / 新建账号共用
const credDialog = ref({
  visible: false,
  title: '',
  username: '',
  password: '',
  hint: ''
})

// 新建账号
const createDialogVisible = ref(false)
const creating = ref(false)
const createForm = ref({
  role: 'student',
  username: '',
  real_name: '',
  gender: '男',
  class_ref: undefined as number | string | undefined,
  is_homeroom: false,
  password: ''
})

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
  classes.value.forEach((c) => map.set(c.id, c.name))
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
    selection.value = []
    tableRef.value?.clearSelection?.()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

async function loadClasses() {
  try {
    classes.value = (await usersApi.classes()).data
  } catch {
    classes.value = []
  }
}

function onSelectionChange(rows: AccountOut[]) {
  selection.value = rows
}

function showCredential(title: string, username: string, password: string, hint: string) {
  credDialog.value = { visible: true, title, username, password, hint }
}

async function resetPassword(id: number) {
  try {
    const res = await usersApi.resetPassword(id)
    showCredential(
      '重置成功',
      res.data.username,
      res.data.temporary_password,
      '把新密码发给本人即可；“打印名单”也会同步显示该密码。'
    )
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '重置失败')
  }
}

function openCreate() {
  createForm.value = {
    role: 'student',
    username: '',
    real_name: '',
    gender: '男',
    class_ref: undefined,
    is_homeroom: false,
    password: ''
  }
  createDialogVisible.value = true
  if (!classes.value.length) loadClasses()
}

async function submitCreate() {
  const f = createForm.value
  if (!f.username.trim() || !f.real_name.trim()) {
    ElMessage.warning('用户名与姓名必填')
    return
  }
  creating.value = true
  try {
    const isAdminRole = f.role === 'school_admin'
    const classPayload =
      isAdminRole || f.class_ref === undefined || f.class_ref === null || f.class_ref === ''
        ? {}
        : typeof f.class_ref === 'number'
          ? { class_id: f.class_ref }
          : { class_name: String(f.class_ref) }
    const res = await usersApi.createAccount({
      role: f.role,
      username: f.username.trim(),
      real_name: f.real_name.trim(),
      gender: f.gender,
      is_homeroom: f.role === 'teacher' ? f.is_homeroom : false,
      password: f.password.trim() || null,
      ...classPayload
    })
    createDialogVisible.value = false
    showCredential(
      '创建成功',
      res.data.username,
      res.data.initial_password,
      res.data.class_name
        ? `班级：${res.data.class_name}。可用“打印名单”把密码下发给本人。`
        : '可用“打印名单”把密码下发给本人。'
    )
    await load()
    await loadClasses()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '创建失败')
  } finally {
    creating.value = false
  }
}

async function removeAccount(row: AccountOut) {
  try {
    await ElMessageBox.confirm(
      `确定删除账号「${row.real_name}（${row.username}）」吗？该账号的测评记录、作答与结果会一并删除，不可恢复。`,
      '删除账号',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' }
    )
  } catch {
    return // 用户取消
  }
  try {
    const res = await usersApi.deleteAccount(row.id)
    ElMessage.success(
      res.data.assessments_removed
        ? `已删除 ${row.username}，同时清理 ${res.data.assessments_removed} 条测评记录`
        : `已删除 ${row.username}`
    )
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

async function batchDelete() {
  const rows = selection.value
  if (!rows.length) return
  const preview = rows
    .slice(0, 8)
    .map((r) => `${r.real_name}（${r.username}）`)
    .join('、')
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${rows.length} 个账号吗？其测评记录、作答与结果会一并删除，不可恢复。\n\n${preview}${rows.length > 8 ? ' 等' : ''}`,
      '批量删除账号',
      { type: 'warning', confirmButtonText: `确认删除 ${rows.length} 个`, cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    const res = await usersApi.batchDeleteAccounts(rows.map((r) => r.id))
    const { deleted_count, skipped } = res.data
    if (skipped.length) {
      const detail = skipped.map((s) => `${s.username || `#${s.id}`}：${s.reason}`).join('<br>')
      await ElMessageBox.alert(
        `已删除 <b>${deleted_count}</b> 个账号，跳过 ${skipped.length} 个：<br>${detail}`,
        '批量删除结果',
        { dangerouslyUseHTMLString: true, confirmButtonText: '知道了' }
      )
    } else {
      ElMessage.success(`已删除 ${deleted_count} 个账号`)
    }
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '批量删除失败')
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

async function bulkResetPasswords() {
  let password: string
  try {
    const { value } = await ElMessageBox.prompt(
      '将把「当前筛选」内的师生密码统一重置为下面的密码（不含管理员）。此操作会覆盖现有密码，重置后首次登录仍需修改。',
      '批量重置密码',
      {
        confirmButtonText: '确认重置',
        cancelButtonText: '取消',
        inputValue: 'Compassio@2026',
        inputPattern: /.{8,}/,
        inputErrorMessage: '密码至少 8 位',
        type: 'warning'
      }
    )
    password = value
  } catch {
    return // 用户取消
  }
  try {
    const res = await usersApi.bulkResetPasswords({
      role: filters.value.role || undefined,
      class_id: filters.value.class_id,
      q: filters.value.q || undefined,
      password
    })
    ElMessage.success(`已重置 ${res.data.reset} 个账号，统一密码：${res.data.password}（可点“打印名单”下发）`)
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '批量重置失败')
  }
}

onMounted(() => {
  load()
  loadClasses()
})
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
        <el-button type="success" plain @click="openCreate">新增账号</el-button>
        <el-button type="danger" plain @click="bulkResetPasswords">批量重置密码</el-button>
        <el-button type="danger" :disabled="!selection.length" @click="batchDelete">
          批量删除{{ selection.length ? `（${selection.length}）` : '' }}
        </el-button>
      </div>

      <el-table
        ref="tableRef"
        :data="accounts"
        v-loading="loading"
        border
        class="account-table"
        @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="44" />
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
        <el-table-column label="操作" width="170">
          <template #default="{ row }">
            <el-button link type="primary" @click="resetPassword(row.id)">重置密码</el-button>
            <el-button link type="danger" @click="removeAccount(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="createDialogVisible" title="新增账号" width="520px">
      <el-form label-width="88px">
        <el-form-item label="角色">
          <el-radio-group v-model="createForm.role">
            <el-radio-button label="student">学生</el-radio-button>
            <el-radio-button label="teacher">教师</el-radio-button>
            <el-radio-button label="school_admin">管理员</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="createForm.username" placeholder="字母/数字/._@-，3–64 位，登录用" />
        </el-form-item>
        <el-form-item label="姓名">
          <el-input v-model="createForm.real_name" placeholder="真实姓名" />
        </el-form-item>
        <el-form-item label="性别">
          <el-radio-group v-model="createForm.gender">
            <el-radio label="男">男</el-radio>
            <el-radio label="女">女</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="createForm.role !== 'school_admin'" label="班级">
          <el-select
            v-model="createForm.class_ref"
            filterable
            allow-create
            default-first-option
            clearable
            placeholder="选择已有班级，或直接输入新班级名"
            style="width: 100%"
          >
            <el-option
              v-for="c in classes"
              :key="c.id"
              :label="c.head_teacher_name ? `${c.name}（班主任：${c.head_teacher_name}）` : c.name"
              :value="c.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="createForm.role === 'teacher'" label="班主任">
          <el-switch v-model="createForm.is_homeroom" />
          <span class="hint">开启后接管所选班级的班主任关系</span>
        </el-form-item>
        <el-form-item label="初始密码">
          <el-input v-model="createForm.password" placeholder="留空自动生成 8 位随机密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="credDialog.visible" :title="credDialog.title" width="380px">
      <p>
        用户名：<strong>{{ credDialog.username }}</strong>
      </p>
      <p>
        密码：<strong>{{ credDialog.password }}</strong>
      </p>
      <p class="hint">{{ credDialog.hint }}</p>
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
  margin-left: 8px;
}
</style>
