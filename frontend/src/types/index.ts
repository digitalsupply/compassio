export interface Token {
  access_token: string
  token_type: string
  role: 'school_admin' | 'teacher' | 'student'
  must_change_password: boolean
}

export interface LoginRequest {
  username: string
  password: string
}

export interface ChangePasswordRequest {
  old_password: string
  new_password: string
}

export interface ScaleBrief {
  scale_id: string
  name: string
  version: string
  audience: string[]
  response_type: string
  item_count: number
  instruction: string
  options: Array<{ value: number; label: string }>
  // 重复测评提示所需状态（问题 2）
  completed: boolean
  completed_at: string | null
  attempts: number
  in_progress: boolean
}

export interface StartAssessmentResponse {
  assessment_id: number
  scale_id: string
  status: string
}

export interface NextItem {
  assessment_id: number
  item_id: number | null
  text: string | null
  transition: string | null
  progress: { answered: number; total: number }
  finished: boolean
  // Layered in by the backend for observability; the UI only uses `source`
  // to surface gentle feedback when the next item came from LLM fusion.
  source?: string | null
  mode?: string | null
}

export interface FinishResponse {
  assessment_id: number
  status: string
  is_valid: boolean | null
  result_id: number | null
}

export interface ReportOut {
  assessment_id: number
  scale_id: string
  scale_name: string
  status: string
  is_valid: boolean | null
  scores: Record<string, any>
  risk_flags: Array<Record<string, any>>
  llm_summary: string | null
  fallback_used: boolean
  created_at: string | null
  attempt_no?: number | null
}

export interface StudentBrief {
  id: number
  real_name: string
  username: string
  gender?: string
  class_name?: string | null
}

export interface MyResultsOut {
  student?: StudentBrief | null
  results: ReportOut[]
}

export interface NotificationOut {
  id: number
  severity: 'info' | 'high' | 'critical'
  title: string
  body: string
  ref_student_id: number | null
  read: boolean
  created_at: string
}

export interface LLMConfigOut {
  id: number
  name: string
  provider_key: string
  base_url: string
  api_key: string | null
  model: string
  extra_headers: Record<string, string>
  is_active: boolean
  timeout_s: number
  is_default: boolean
}

export interface LLMConfigIn {
  name: string
  provider_key: string
  base_url: string
  api_key: string | null
  model: string
  extra_headers: Record<string, string>
  is_active: boolean
  timeout_s: number
  is_default: boolean
}

export interface ScaleDefOut {
  scale_id: string
  version: string
  loaded_at: string
  item_count: number
}

export interface ImportRowError {
  row: number
  message: string
}

export interface ImportPreview {
  kind: string
  total_rows: number
  accounts: Array<Record<string, any>>
  warnings: string[]
  errors: ImportRowError[]
}

export interface ImportCommitResult {
  kind: string
  created: number
  errors: ImportRowError[]
  roster_html: string
}

export interface AccountOut {
  id: number
  role: string
  username: string
  real_name: string
  gender: string
  phone: string | null
  class_id: number | null
  class_name: string | null
  is_homeroom: boolean
  is_active: boolean
  must_change_password: boolean
}

export interface ClassOut {
  id: number
  name: string
  grade_level: string
  head_teacher_id: number | null
  head_teacher_name: string | null
}

export interface AccountCreateIn {
  role: string
  username: string
  real_name: string
  gender?: string
  phone?: string | null
  class_id?: number | null
  class_name?: string | null
  is_homeroom?: boolean
  password?: string | null
}

export interface AccountCreated {
  id: number
  role: string
  username: string
  real_name: string
  class_name: string | null
  is_homeroom: boolean
  initial_password: string
}

export interface AccountDeleted {
  id: number
  role: string
  username: string
  assessments_removed: number
}

export interface BatchDeleteResult {
  deleted: AccountDeleted[]
  skipped: { id: number; username: string | null; reason: string }[]
  deleted_count: number
  skipped_count: number
}

export interface ClassReport {
  class_id: number
  class_name: string
  grade_level: string
  head_teacher_id: number | null
  head_teacher_name: string | null
  student_count: number
  completed_count: number
  completion_rate: number
  dimension_means: Record<string, number>
  risk_counts: Record<string, number>
  total: number
  completed: number
  pending: number
}

export interface TeacherClassSummary {
  class_id: number
  class_name: string
  scale_id: string
  total: number
  completed: number
  pending: number
  completion_rate: number
}

export interface TeacherClassResultOut {
  assessment_id: number
  student_name: string
  username: string
  class_name: string
  gender: string
  scale_id: string
  scale_name: string
  attempt_no?: number | null
  status: string
  is_valid: boolean | null
  scores: Record<string, any>
  risk_flags: Array<Record<string, any>>
  llm_summary: string | null
  fallback_used: boolean
  completed_at: string | null
  created_at: string | null
}
