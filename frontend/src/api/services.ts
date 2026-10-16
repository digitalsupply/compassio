import client from './client'
import type {
  AccountCreateIn,
  AccountCreated,
  AccountDeleted,
  AccountOut,
  BatchDeleteResult,
  ChangePasswordRequest,
  ClassOut,
  ClassReport,
  ImportCommitResult,
  ImportPreview,
  LLMConfigIn,
  LLMConfigOut,
  LoginRequest,
  MyResultsOut,
  NextItem,
  NotificationOut,
  ReportOut,
  ScaleBrief,
  ScaleDefOut,
  StartAssessmentResponse,
  TeacherClassResultOut,
  TeacherClassSummary,
  Token
} from '@/types'

export function filenameFromDisposition(disposition: string | undefined, fallback: string): string {
  if (!disposition) return fallback
  const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (star) {
    try {
      return decodeURIComponent(star[1])
    } catch {
      return fallback
    }
  }
  const quoted = /filename="?([^";]+)"?/i.exec(disposition)
  if (quoted) {
    try {
      return decodeURIComponent(quoted[1])
    } catch {
      return quoted[1]
    }
  }
  return fallback
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export function downloadResponse(
  res: { data: Blob; headers: Record<string, any> },
  fallbackName: string
): void {
  const disposition =
    res.headers?.['content-disposition'] || res.headers?.['Content-Disposition']
  saveBlob(res.data as Blob, filenameFromDisposition(disposition, fallbackName))
}

export const authApi = {
  login: (data: LoginRequest) => client.post<Token>('/auth/login', data),
  changePassword: (data: ChangePasswordRequest) =>
    client.post<{ ok: boolean }>('/auth/change-password', data)
}

export const assessApi = {
  scales: () => client.get<ScaleBrief[]>('/assess/scales'),
  start: (scale_id: string) =>
    client.post<StartAssessmentResponse>('/assess/start', { scale_id }),
  next: (id: number) => client.get<NextItem>(`/assess/${id}/next`),
  answer: (id: number, item_id: number, value: number) =>
    client.post<{ ok: boolean; risk_flags: any[] }>(`/assess/${id}/answer`, {
      item_id,
      value
    }),
  finish: (id: number) => client.post<any>(`/assess/${id}/finish`),
  myResults: () => client.get<MyResultsOut>('/assess/my-results'),
  report: (id: number) => client.get<ReportOut>(`/assess/${id}/report`)
}

export const usersApi = {
  accounts: (params?: { role?: string; class?: number; q?: string }) =>
    client.get<AccountOut[]>('/admin/accounts', { params }),
  classes: () => client.get<ClassOut[]>('/admin/classes'),
  createAccount: (data: AccountCreateIn) =>
    client.post<AccountCreated>('/admin/accounts', data),
  deleteAccount: (id: number) => client.delete<AccountDeleted>(`/admin/accounts/${id}`),
  batchDeleteAccounts: (user_ids: number[]) =>
    client.post<BatchDeleteResult>('/admin/accounts/batch-delete', { user_ids }),
  resetPassword: (id: number) =>
    client.post<{ username: string; temporary_password: string }>(
      `/admin/accounts/${id}/reset-password`
    ),
  printRoster: (params?: { role?: string; class_id?: number }) =>
    client.get<string>('/admin/accounts/print-roster', { params }),
  bulkResetPasswords: (data: {
    role?: string
    class_id?: number
    q?: string
    password?: string
  }) =>
    client.post<{ reset: number; password: string }>(
      '/admin/accounts/reset-passwords',
      data
    )
}

export const notifyApi = {
  list: (unread?: boolean) =>
    client.get<NotificationOut[]>('/notify/list', { params: { unread } }),
  markRead: (id: number) => client.post<{ ok: boolean }>(`/notify/${id}/read`),
  unreadCount: () => client.get<{ count: number }>('/notify/unread-count')
}

export const reportApi = {
  classes: (scale_id?: string) =>
    client.get<ClassReport[]>('/admin/reports/classes', { params: { scale_id } }),
  exportClass: (class_id: number, scale_id: string, format: 'xlsx' | 'csv') =>
    client.get<Blob>('/admin/reports/export', {
      params: { class_id, scale_id, format },
      responseType: 'blob'
    })
}

export const teacherApi = {
  classSummary: (scale_id: string) =>
    client.get<TeacherClassSummary>('/teacher/class-summary', { params: { scale_id } }),
  classResults: (scale_id: string) =>
    client.get<TeacherClassResultOut[]>('/teacher/class-results', { params: { scale_id } }),
  classExport: (scale_id: string, format: 'xlsx' | 'csv', class_id?: number) =>
    client.get<Blob>('/teacher/class-export', {
      params: { scale_id, format, class_id },
      responseType: 'blob'
    })
}

export const llmApi = {
  list: () => client.get<LLMConfigOut[]>('/admin/llm-configs'),
  create: (data: LLMConfigIn) =>
    client.post<LLMConfigOut>('/admin/llm-configs', data),
  update: (id: number, data: LLMConfigIn) =>
    client.put<LLMConfigOut>(`/admin/llm-configs/${id}`, data),
  delete: (id: number) => client.delete<{ ok: boolean }>(`/admin/llm-configs/${id}`),
  test: (id: number) => client.post<{ ok: boolean }>(`/admin/llm-configs/${id}/test`)
}

export const scalesApi = {
  list: () => client.get<ScaleDefOut[]>('/admin/scales'),
  reload: (scale_id: string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return client.post<{ scale_id: string; version: string }>(
      `/admin/scales/${scale_id}/reload`,
      fd
    )
  }
}

export const importApi = {
  template: (kind: 'teachers' | 'students') =>
    client.get(`/import/template/${kind}`, { responseType: 'blob' }),
  preview: (kind: 'teachers' | 'students', file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return client.post<ImportPreview>(`/import/${kind}`, fd)
  },
  commit: (kind: 'teachers' | 'students', file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return client.post<ImportCommitResult>(`/import/${kind}/commit`, fd)
  }
}
