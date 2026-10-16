<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useNotifyStore } from '@/stores/notify'
import CompassioLogo from './CompassioLogo.vue'

const auth = useAuthStore()
const notify = useNotifyStore()
const route = useRoute()
const router = useRouter()

const nav = computed(() => {
  if (auth.isAdmin) {
    return [
      { label: '通知中心', path: '/admin/notifications' },
      { label: '导入师生', path: '/admin/import' },
      { label: '账号管理', path: '/admin/accounts' },
      { label: '班级报告', path: '/admin/class-reports' },
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

// full=已登录导航；simple=落地页顶部（仅品牌+登录）；none=登录/改密页不显示
const mode = computed<'full' | 'simple' | 'none'>(() => {
  if (auth.isLoggedIn) return route.name === 'ChangePassword' ? 'none' : 'full'
  return route.name === 'Home' ? 'simple' : 'none'
})

function logout() {
  auth.logout()
  router.push('/login')
}

function goLogin() {
  router.push('/login')
}
</script>

<template>
  <header v-if="mode !== 'none'" class="app-header">
    <router-link to="/" class="brand">
      <CompassioLogo :size="36" />
      <div class="brand-text">
        <span class="name">Compassio</span>
        <span class="slogan">心育罗盘 · 提前指引，向阳成长</span>
      </div>
    </router-link>
    <nav v-if="mode === 'full'" class="nav">
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
    <div v-else class="nav">
      <el-button type="primary" round @click="goLogin">登录</el-button>
    </div>
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
  text-decoration: none;
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
