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
}

export interface MyResultsOut {
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
}
