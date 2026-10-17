from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    must_change_password: bool


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=8)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    username: str
    real_name: str
    gender: str
    phone: str | None
    class_id: int | None
    is_homeroom: bool
    is_active: bool
    must_change_password: bool


class ClassOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    grade_level: str
    head_teacher_id: int | None
    head_teacher_name: str | None = None


class ScaleBrief(BaseModel):
    scale_id: str
    name: str
    version: str
    audience: list[str]
    response_type: str
    item_count: int
    instruction: str
    options: list[dict]
    # 该学生在该量表上的完成/作答状态（问题 2：重复测评提示所需）
    completed: bool = False
    completed_at: datetime | None = None
    attempts: int = 0
    in_progress: bool = False


class StartAssessmentRequest(BaseModel):
    scale_id: str


class StartAssessmentResponse(BaseModel):
    assessment_id: int
    scale_id: str
    status: str


class AnswerRequest(BaseModel):
    item_id: int
    value: int


class NextItem(BaseModel):
    assessment_id: int
    item_id: int | None
    text: str | None
    transition: str | None
    progress: dict
    finished: bool
    # 新增（保持兼容，前端可忽略）：选题来源与当前策略，供指标/调试使用。
    source: str | None = None
    mode: str | None = None


class FinishResponse(BaseModel):
    assessment_id: int
    status: str
    is_valid: bool | None
    result_id: int | None


class ReportOut(BaseModel):
    assessment_id: int
    scale_id: str
    scale_name: str
    status: str
    is_valid: bool | None
    scores: dict[str, Any]
    risk_flags: list[dict]
    llm_summary: str | None
    fallback_used: bool
    created_at: datetime | None
    # 第几次尝试（同一量表按时间排序，从 1 开始），用于「第 2 次测评」标注。
    attempt_no: int | None = None


class StudentBrief(BaseModel):
    """当前登录学生本人的基本信息（仅返回自己，用于报告页呈现）。"""

    id: int
    real_name: str
    username: str
    gender: str = ""
    class_name: str | None = None


class MyResultsOut(BaseModel):
    student: StudentBrief | None = None
    results: list[ReportOut]


class TeacherClassResultOut(BaseModel):
    """班主任「本班学生结果」行：学生身份 + 测评结果（仅学生量表）。

    硬约束：teacher_ref（教师量表）永不进入本响应。
    """

    assessment_id: int
    student_name: str
    username: str
    class_name: str
    gender: str
    scale_id: str
    scale_name: str
    attempt_no: int | None = None
    status: str
    is_valid: bool | None
    scores: dict[str, Any]
    risk_flags: list[dict]
    llm_summary: str | None
    fallback_used: bool
    completed_at: datetime | None
    # 保留给报告卡组件（ReportCard 读取 created_at 作为完成时间展示）。
    created_at: datetime | None = None


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    severity: str
    title: str
    body: str
    ref_student_id: int | None
    read: bool
    created_at: datetime


class LLMConfigIn(BaseModel):
    name: str
    provider_key: str
    base_url: str
    api_key: str | None = None
    model: str
    extra_headers: dict = Field(default_factory=dict)
    is_active: bool = True
    timeout_s: int = 30
    is_default: bool = False


def mask_api_key(value: str | None) -> str | None:
    """Mask a secret for display: keep a short prefix/suffix, never the whole key."""
    if not value:
        return None
    if len(value) <= 8:
        return "****"
    return f"{value[:3]}****{value[-4:]}"


class LLMConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    provider_key: str
    base_url: str
    api_key: str | None
    model: str
    extra_headers: dict
    is_active: bool
    timeout_s: int
    is_default: bool

    @field_serializer("api_key")
    def _serialize_api_key(self, value: str | None) -> str | None:
        # 出参一律掩码：明文密钥绝不离开服务端（入库/调用仍在后端完成）。
        return mask_api_key(value)


class ScaleDefOut(BaseModel):
    scale_id: str
    version: str
    loaded_at: datetime
    item_count: int


class ImportRowError(BaseModel):
    row: int
    message: str


class ImportPreview(BaseModel):
    kind: str
    total_rows: int
    accounts: list[dict]
    warnings: list[str]
    errors: list[ImportRowError]


class ImportCommitResult(BaseModel):
    kind: str
    created: int
    errors: list[ImportRowError]
    roster_html: str


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    username: str
    real_name: str
    gender: str
    phone: str | None
    class_id: int | None
    class_name: str | None
    is_homeroom: bool
    is_active: bool
    must_change_password: bool


class BulkResetPasswordIn(BaseModel):
    """按当前筛选批量重置密码（管理员用，不含管理员自身）。"""

    role: str | None = None
    class_id: int | None = None
    q: str | None = None
    password: str | None = None


class AccountCreateIn(BaseModel):
    """管理员手工新增单个账号（测试数据/临时账号）。"""

    role: str
    username: str
    real_name: str
    gender: str = "男"
    phone: str | None = None
    # 班级二选一：class_id 优先；class_name 不存在时会按导入同样的规则新建
    class_id: int | None = None
    class_name: str | None = None
    is_homeroom: bool = False
    # 留空则自动生成 8 位初始密码
    password: str | None = None


class AccountCreatedOut(BaseModel):
    id: int
    role: str
    username: str
    real_name: str
    class_name: str | None = None
    is_homeroom: bool = False
    initial_password: str


class AccountDeleteResult(BaseModel):
    id: int
    role: str
    username: str
    assessments_removed: int = 0


class SkippedAccount(BaseModel):
    id: int
    username: str | None = None
    reason: str


class BatchDeleteIn(BaseModel):
    user_ids: list[int]


class BatchDeleteResult(BaseModel):
    deleted: list[AccountDeleteResult]
    skipped: list[SkippedAccount]
    deleted_count: int
    skipped_count: int


class ClassReport(BaseModel):
    class_id: int
    class_name: str
    grade_level: str
    head_teacher_id: int | None
    head_teacher_name: str | None
    student_count: int
    completed_count: int
    completion_rate: float
    dimension_means: dict[str, float]
    risk_counts: dict[str, int]
    # 问题 3：分发/导出所需的完成统计（total=学生数，pending=未完成数）
    total: int = 0
    completed: int = 0
    pending: int = 0


class TeacherClassSummary(BaseModel):
    class_id: int
    class_name: str
    scale_id: str
    total: int
    completed: int
    pending: int
    completion_rate: float


class HealthOut(BaseModel):
    db: bool
    redis: bool
    llm: bool
