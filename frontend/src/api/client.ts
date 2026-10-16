import axios from 'axios'

const client = axios.create({
  baseURL: '/api',
  timeout: 30000
})

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('compassio_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

client.interceptors.response.use(
  (response) => response,
  (error) => {
    const url: string = error.config?.url || ''
    // 登录/改密接口的 401 属于业务校验（如密码错误），交给页面提示，不能整页跳转
    const isAuthCall = url.includes('/auth/login') || url.includes('/auth/change-password')
    if (error.response?.status === 401 && !isAuthCall) {
      localStorage.removeItem('compassio_token')
      localStorage.removeItem('compassio_role')
      localStorage.removeItem('compassio_must_change')
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)

export default client
