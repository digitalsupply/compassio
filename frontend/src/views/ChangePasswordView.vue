<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { authApi } from '@/api/services'
import { useAuthStore } from '@/stores/auth'
import CompassioLogo from '@/components/CompassioLogo.vue'

const router = useRouter()
const auth = useAuthStore()

const form = ref({ old_password: '', new_password: '', confirm: '' })
const loading = ref(false)

onMounted(() => {
  if (!auth.isLoggedIn) {
    router.replace('/login')
  }
})

async function submit() {
  if (!form.value.old_password || !form.value.new_password) {
    ElMessage.warning('请填写完整')
    return
  }
  if (form.value.new_password.length < 8) {
    ElMessage.warning('新密码至少 8 位')
    return
  }
  if (form.value.new_password !== form.value.confirm) {
    ElMessage.error('两次输入的新密码不一致')
    return
  }
  loading.value = true
  try {
    await authApi.changePassword({
      old_password: form.value.old_password,
      new_password: form.value.new_password
    })
    auth.setMustChange(false)
    ElMessage.success('密码修改成功')
    router.replace('/')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '修改失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="brand">
        <CompassioLogo :size="56" />
        <h1>首次登录，修改密码</h1>
        <p class="slogan">为了账号安全，请设置新密码。</p>
      </div>
      <el-form :model="form" label-position="top" @submit.prevent="submit">
        <el-form-item label="当前密码">
          <el-input v-model="form.old_password" type="password" placeholder="初始密码" show-password />
        </el-form-item>
        <el-form-item label="新密码（至少 8 位）">
          <el-input v-model="form.new_password" type="password" placeholder="新密码" show-password />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="form.confirm" type="password" placeholder="再次输入新密码" show-password />
        </el-form-item>
        <el-button type="primary" size="large" native-type="submit" :loading="loading" class="submit">
          确认修改
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fff7ed;
}
.login-card {
  width: 380px;
  background: #fff;
  padding: 32px;
  border-radius: 12px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.06);
}
.brand {
  text-align: center;
  margin-bottom: 24px;
}
.brand h1 {
  margin: 12px 0 4px;
  font-size: 22px;
  color: #1f2937;
}
.slogan {
  color: #6b7280;
  font-size: 14px;
}
.submit {
  width: 100%;
  margin-top: 8px;
}
</style>
