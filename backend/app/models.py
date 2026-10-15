import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.db import JsonType


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class UserRole(str, enum.Enum):
    SCHOOL_ADMIN = "school_admin"
    TEACHER = "teacher"
    STUDENT = "student"


class GradeLevel(str, enum.Enum):
    PRIMARY_G4 = "primary_g4"
    JUNIOR = "junior"
    SENIOR = "senior"


class AssessmentStatus(str, enum.Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class NotificationSeverity(str, enum.Enum):
    INFO = "info"
    HIGH = "high"
    CRITICAL = "critical"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    role: Mapped[UserRole]
    username: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    password_hash: Mapped[str]
    # 初始密码明文：仅供管理员打印/下发账号名单；账号本人自助改密后清空。
    initial_password: Mapped[Optional[str]] = mapped_column(
        sa.String(64), nullable=True
    )
    must_change_password: Mapped[bool] = mapped_column(default=True)
    real_name: Mapped[str] = mapped_column(sa.String(64))
    gender: Mapped[str] = mapped_column(sa.String(8))
    phone: Mapped[Optional[str]] = mapped_column(sa.String(32), nullable=True)
    # 学生：所在班级；教师：所关联/所带班级（见 is_homeroom）
    class_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("classes.id", use_alter=True), nullable=True
    )
    # 教师是否为 class_id 对应班级的班主任（学生恒为 False）。
    # 同名教师通过 (class_id, is_homeroom) 区分，班级与班主任的对应关系统一由
    # Class.head_teacher_id + 本字段共同保证。
    is_homeroom: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=now_utc)

    cls: Mapped[Optional["Class"]] = relationship(
        "Class", foreign_keys=[class_id], lazy="selectin"
    )  # async 下惰性加载会抛 MissingGreenlet，统一预加载
    assessments: Mapped[list["Assessment"]] = relationship(
        "Assessment", back_populates="user", lazy="selectin", foreign_keys="Assessment.user_id"
    )


class Class(Base):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(sa.String(64), unique=True)
    grade_level: Mapped[GradeLevel]
    head_teacher_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("users.id", use_alter=True), nullable=True
    )

    students: Mapped[list[User]] = relationship(
        "User",
        foreign_keys="User.class_id",
        primaryjoin=lambda: sa.and_(Class.id == User.class_id, User.role == UserRole.STUDENT),
        viewonly=True,
    )
    teachers: Mapped[list[User]] = relationship(
        "User",
        foreign_keys="User.class_id",
        primaryjoin=lambda: sa.and_(Class.id == User.class_id, User.role == UserRole.TEACHER),
        viewonly=True,
    )
    head_teacher: Mapped[Optional[User]] = relationship("User", foreign_keys=[head_teacher_id])


class ScaleDef(Base):
    __tablename__ = "scale_defs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scale_id: Mapped[str] = mapped_column(sa.String(32), unique=True, index=True)
    version: Mapped[str]
    loaded_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=now_utc)
    payload: Mapped[dict] = mapped_column(JsonType)


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"))
    scale_id: Mapped[str]
    status: Mapped[AssessmentStatus] = mapped_column(default=AssessmentStatus.IN_PROGRESS)
    started_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=now_utc)
    completed_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    item_order: Mapped[list] = mapped_column(JsonType, default=list)
    is_valid: Mapped[Optional[bool]] = mapped_column(nullable=True)
    invalidated_reason: Mapped[Optional[str]] = mapped_column(nullable=True)
    # DEPRECATED: 手动「分发结果」已移除，教师端改为按本班学生+已完成自动可见。
    # 列保留仅为避免迁移风险，代码不再读写。
    distributed_to_teacher_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    distributed_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="assessments", foreign_keys=[user_id])
    responses: Mapped[list["Response"]] = relationship(
        "Response", back_populates="assessment", lazy="selectin"
    )
    result: Mapped["Result | None"] = relationship(
        "Result", back_populates="assessment", uselist=False, lazy="selectin"
    )


class Response(Base):
    __tablename__ = "responses"
    __table_args__ = (sa.UniqueConstraint("assessment_id", "item_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    assessment_id: Mapped[int] = mapped_column(sa.ForeignKey("assessments.id"))
    item_id: Mapped[int]
    value: Mapped[int]
    answered_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=now_utc)

    assessment: Mapped[Assessment] = relationship("Assessment", back_populates="responses")


class Result(Base):
    __tablename__ = "results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    assessment_id: Mapped[int] = mapped_column(sa.ForeignKey("assessments.id"), unique=True)
    scores: Mapped[dict] = mapped_column(JsonType)
    risk_flags: Mapped[list] = mapped_column(JsonType, default=list)
    llm_summary: Mapped[Optional[str]] = mapped_column(sa.Text, nullable=True)
    fallback_used: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=now_utc)

    assessment: Mapped[Assessment] = relationship(
        "Assessment", back_populates="result"
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    recipient_role: Mapped[UserRole]
    severity: Mapped[NotificationSeverity]
    title: Mapped[str]
    body: Mapped[str] = mapped_column(sa.Text)
    ref_student_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("users.id"), nullable=True
    )
    read: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=now_utc)


class LLMConfig(Base):
    __tablename__ = "llm_configs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str]
    provider_key: Mapped[str]
    base_url: Mapped[str]
    api_key: Mapped[Optional[str]]
    model: Mapped[str]
    extra_headers: Mapped[dict] = mapped_column(JsonType, default=dict)
    is_active: Mapped[bool] = mapped_column(default=True)
    timeout_s: Mapped[int] = mapped_column(default=30)
    is_default: Mapped[bool] = mapped_column(default=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    actor_id: Mapped[Optional[int]] = mapped_column(sa.ForeignKey("users.id"), nullable=True)
    action: Mapped[str]
    detail: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), default=now_utc)
