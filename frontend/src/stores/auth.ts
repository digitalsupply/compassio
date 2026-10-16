import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/services'
import type { LoginRequest } from '@/types'

export const KNOWN_ROLES = ['school_admin', 'teacher', 'student'] as const
type Role = (typeof KNOWN_ROLES)[number]

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('compassio_token') || '')
  const role = ref<Role | ''>((localStorage.getItem('compassio_role') as any) || '')
  const mustChange = ref(localStorage.getItem('compassio_must_change') === '1')

  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => role.value === 'school_admin')
  const isTeacher = computed(() => role.value === 'teacher')
  const isStudent = computed(() => role.value === 'student')

  /** 会话是否完整可信（token + 合法角色），用于避免脏 localStorage 造成的跳转死循环。 */
  const hasValidSession = computed(
    () => !!token.value && (KNOWN_ROLES as readonly string[]).includes(role.value)
  )

  function persistMustChange(value: boolean) {
    mustChange.value = value
    if (value) localStorage.setItem('compassio_must_change', '1')
    else localStorage.removeItem('compassio_must_change')
  }

  async function login(data: LoginRequest) {
    const res = await authApi.login(data)
    token.value = res.data.access_token
    role.value = res.data.role as Role
    localStorage.setItem('compassio_token', res.data.access_token)
    localStorage.setItem('compassio_role', res.data.role)
    persistMustChange(!!res.data.must_change_password)
    return res.data
  }

  function logout() {
    token.value = ''
    role.value = ''
    mustChange.value = false
    localStorage.removeItem('compassio_token')
    localStorage.removeItem('compassio_role')
    localStorage.removeItem('compassio_must_change')
    localStorage.removeItem('compassio_current_assessment')
  }

  /** 清理 token/角色不一致等脏会话（不触发路由，供守卫使用）。 */
  function clearSession() {
    token.value = ''
    role.value = ''
    mustChange.value = false
    localStorage.removeItem('compassio_token')
    localStorage.removeItem('compassio_role')
    localStorage.removeItem('compassio_must_change')
  }

  function setRole(r: string) {
    role.value = r as Role
    localStorage.setItem('compassio_role', r)
  }

  return {
    token,
    role,
    mustChange,
    isLoggedIn,
    isAdmin,
    isTeacher,
    isStudent,
    hasValidSession,
    login,
    logout,
    clearSession,
    setRole,
    setMustChange: persistMustChange
  }
})
