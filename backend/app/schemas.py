from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


class MyResultsOut(BaseModel):
    results: list[ReportOut]


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


class HealthOut(BaseModel):
    db: bool
    redis: bool
    llm: bool
