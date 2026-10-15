<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useNotifyStore } from '@/stores/notify'
import CompassioLogo from './CompassioLogo.vue'

const auth = useAuthStore()
const notify = useNotifyStore()
const router = useRouter()

const nav = computed(() => {
  if (auth.isAdmin) {
    return [
      { label: '通知中心', path: '/admin/notifications' },
      { label: '导入师生', path: '/admin/import' },
      { label: '账号管理', path: '/admin/accounts' },
      { label: '班级报告', path: '/admin/class-reports' },
      { label: '分发结果', path: '/admin/dispatch' },
      { label: 'LLM 配置', path: '/admin/llm' },
      { label: '题目库', path: '/admin/scales' }
    ]
  }
  if (auth.isTeacher) {
    return [
      { label: '我的测评', path: '/teacher' },
      { label: '我的报告', path: '/teacher/reports' },
      { label: '本班学生结果', path: '/teacher/class-results' }
    ]
  }
  if (auth.isStudent) {
    return [
      { label: '首页', path: '/student' },
      { label: '我的报告', path: '/student/reports' }
    ]
  }
  return []
})

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <header class="app-header" v-if="auth.isLoggedIn">
    <div class="brand">
      <CompassioLogo :size="36" />
      <div class="brand-text">
        <span class="name">Compassio</span>
        <span class="slogan">提前指引，向阳成长。</span>
      </div>
    </div>
    <nav class="nav">
      <router-link
        v-for="item in nav"
        :key="item.path"
        :to="item.path"
        class="nav-link"
        active-class="active"
      >
        {{ item.label }}
        <span v-if="item.path === '/admin/notifications' && notify.unreadCount > 0" class="badge">
          {{ notify.unreadCount }}
        </span>
      </router-link>
      <el-button link type="primary" @click="logout" class="logout">退出</el-button>
    </nav>
  </header>
</template>

<style scoped>
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  background: #fff;
  border-bottom: 1px solid #e5e7eb;
  position: sticky;
  top: 0;
  z-index: 100;
}
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}
.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}
.name {
  font-weight: 700;
  font-size: 18px;
  color: #1f2937;
}
.slogan {
  font-size: 12px;
  color: #6b7280;
}
.nav {
  display: flex;
  align-items: center;
  gap: 18px;
}
.nav-link {
  color: #4b5563;
  text-decoration: none;
  font-size: 14px;
  position: relative;
}
.nav-link:hover,
.nav-link.active {
  color: #3b82f6;
}
.badge {
  display: inline-block;
  margin-left: 4px;
  padding: 0 6px;
  border-radius: 10px;
  background: #ef4444;
  color: #fff;
  font-size: 12px;
  line-height: 16px;
}
.logout {
  margin-left: 8px;
}
@media print {
  .app-header {
    display: none !important;
  }
}
</style>
