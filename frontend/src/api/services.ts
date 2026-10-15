import client from './client'
import type {
  AccountOut,
  ChangePasswordRequest,
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
  Token
} from '@/types'

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
  resetPassword: (id: number) =>
    client.post<{ username: string; temporary_password: string }>(
      `/admin/accounts/${id}/reset-password`
    ),
  printRoster: (params?: { role?: string; class_id?: number }) =>
    client.get<string>('/admin/accounts/print-roster', { params })
}

export const notifyApi = {
  list: (unread?: boolean) =>
    client.get<NotificationOut[]>('/notify/list', { params: { unread } }),
  markRead: (id: number) => client.post<{ ok: boolean }>(`/notify/${id}/read`),
  unreadCount: () => client.get<{ count: number }>('/notify/unread-count')
}

export const reportApi = {
  classes: () => client.get<ClassReport[]>('/admin/reports/classes'),
  dispatch: (class_id: number) =>
    client.post<{ dispatched: number }>('/admin/reports/dispatch', { class_id }),
  teacherClassResults: () =>
    client.get<ReportOut[]>('/teacher/class-students-results')
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
