import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import LoginView from '@/views/LoginView.vue'
import ChangePasswordView from '@/views/ChangePasswordView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: LoginView,
      meta: { public: true }
    },
    {
      path: '/change-password',
      name: 'ChangePassword',
      component: ChangePasswordView
    },
    {
      path: '/',
      name: 'Home',
      component: () => import('@/views/HomeView.vue'),
      meta: { public: true }
    },
    {
      path: '/student',
      name: 'StudentHome',
      component: () => import('@/views/student/StudentHome.vue'),
      meta: { role: 'student' }
    },
    {
      path: '/student/assess/:id',
      name: 'StudentAssess',
      component: () => import('@/views/student/StudentAssess.vue'),
      props: true,
      meta: { role: 'student' }
    },
    {
      path: '/student/reports',
      name: 'StudentReports',
      component: () => import('@/views/student/StudentReports.vue'),
      meta: { role: 'student' }
    },
    {
      path: '/teacher',
      name: 'TeacherAssess',
      component: () => import('@/views/teacher/TeacherAssess.vue'),
      meta: { role: 'teacher' }
    },
    {
      path: '/teacher/reports',
      name: 'TeacherReports',
      component: () => import('@/views/teacher/TeacherReports.vue'),
      meta: { role: 'teacher' }
    },
    {
      path: '/teacher/class-results',
      name: 'TeacherClassResults',
      component: () => import('@/views/teacher/TeacherClassResults.vue'),
      meta: { role: 'teacher' }
    },
    {
      path: '/admin/import',
      name: 'AdminImport',
      component: () => import('@/views/admin/AdminImport.vue'),
      meta: { role: 'school_admin' }
    },
    {
      path: '/admin/accounts',
      name: 'AdminAccounts',
      component: () => import('@/views/admin/AdminAccounts.vue'),
      meta: { role: 'school_admin' }
    },
    {
      path: '/admin/notifications',
      name: 'AdminNotifications',
      component: () => import('@/views/admin/AdminNotifications.vue'),
      meta: { role: 'school_admin' }
    },
    {
      path: '/admin/class-reports',
      name: 'AdminClassReports',
      component: () => import('@/views/admin/AdminClassReports.vue'),
      meta: { role: 'school_admin' }
    },
    {
      path: '/admin/llm',
      name: 'AdminLLMConfig',
      component: () => import('@/views/admin/AdminLLMConfig.vue'),
      meta: { role: 'school_admin' }
    },
    {
      path: '/admin/scales',
      name: 'AdminScales',
      component: () => import('@/views/admin/AdminScales.vue'),
      meta: { role: 'school_admin' }
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/'
    }
  ]
})

router.beforeEach((to) => {
  const auth = useAuthStore()

  // 1) 脏会话：token 与角色不一致 → 清理，避免「首页↔守卫」来回跳转卡在"正在跳转…"
  if (!auth.hasValidSession && (auth.token || auth.role)) {
    auth.clearSession()
  }

  const authed = auth.hasValidSession

  // 2) 首次登录强制改密：除改密页外，一律先去改密
  if (authed && auth.mustChange && to.name !== 'ChangePassword') {
    return { name: 'ChangePassword' }
  }

  // 3) 已登录访问登录页 → 回到自己的首页
  if (to.name === 'Login') {
    return authed ? { path: '/' } : true
  }

  // 4) 公开页（首页 Landing / 登录）放行
  if (to.meta.public) return true

  // 5) 未登录 → 登录页
  if (!authed) return { name: 'Login' }

  // 6) 角色不匹配 → 回到自己的首页（由首页按角色再分流）
  if (to.meta.role && to.meta.role !== auth.role) {
    return { path: '/' }
  }

  return true
})

export default router
