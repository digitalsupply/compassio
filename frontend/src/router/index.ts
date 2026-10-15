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
      component: ChangePasswordView,
      meta: { public: true }
    },
    {
      path: '/',
      name: 'Home',
      component: () => import('@/views/HomeRedirect.vue')
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
      path: '/admin/dispatch',
      name: 'AdminDispatch',
      component: () => import('@/views/admin/AdminDispatch.vue'),
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
    }
  ]
})

router.beforeEach((to, from, next) => {
  const auth = useAuthStore()
  const token = localStorage.getItem('compassio_token')
  const role = localStorage.getItem('compassio_role') || ''

  if (to.meta.public && token) {
    return next('/')
  }
  if (!to.meta.public && !token) {
    return next('/login')
  }
  if (to.meta.role && to.meta.role !== role) {
    return next('/')
  }
  next()
})

export default router
