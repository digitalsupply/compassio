<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import CompassioLogo from '@/components/CompassioLogo.vue'

const router = useRouter()
const auth = useAuthStore()

const form = ref({ username: '', password: '' })
const loading = ref(false)

async function submit() {
  if (!form.value.username || !form.value.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const data = await auth.login({
      username: form.value.username,
      password: form.value.password
    })
    ElMessage.success('登录成功')
    if (data.must_change_password) {
      router.replace('/change-password')
    } else {
      router.replace('/')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="brand">
        <CompassioLogo :size="64" />
        <h1>Compassio</h1>
        <p class="slogan">提前指引，向阳成长。</p>
      </div>
      <el-form :model="form" label-position="top" @submit.prevent="submit">
        <el-form-item label="用户名">
          <el-input v-model="form.username" placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" placeholder="请输入密码" show-password />
        </el-form-item>
        <el-button type="primary" size="large" native-type="submit" :loading="loading" class="submit">
          登录
        </el-button>
      </el-form>
      <p class="notice">本系统结果属于发展性筛查参考，不构成医学诊断。</p>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #eff6ff 0%, #fff 100%);
}
.login-card {
  width: 360px;
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
  font-size: 28px;
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
.notice {
  margin-top: 16px;
  font-size: 12px;
  color: #9ca3af;
  text-align: center;
}
</style>
