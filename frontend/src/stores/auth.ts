import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/services'
import type { LoginRequest } from '@/types'

const roles = ['school_admin', 'teacher', 'student'] as const

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('compassio_token') || '')
  const role = ref<(typeof roles)[number] | ''>(
    (localStorage.getItem('compassio_role') as any) || ''
  )

  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => role.value === 'school_admin')
  const isTeacher = computed(() => role.value === 'teacher')
  const isStudent = computed(() => role.value === 'student')

  async function login(data: LoginRequest) {
    const res = await authApi.login(data)
    token.value = res.data.access_token
    role.value = res.data.role
    localStorage.setItem('compassio_token', res.data.access_token)
    localStorage.setItem('compassio_role', res.data.role)
    return res.data
  }

  function logout() {
    token.value = ''
    role.value = ''
    localStorage.removeItem('compassio_token')
    localStorage.removeItem('compassio_role')
    localStorage.removeItem('compassio_current_assessment')
  }

  function setRole(r: string) {
    role.value = r as any
    localStorage.setItem('compassio_role', r)
  }

  return {
    token,
    role,
    isLoggedIn,
    isAdmin,
    isTeacher,
    isStudent,
    login,
    logout,
    setRole
  }
})
