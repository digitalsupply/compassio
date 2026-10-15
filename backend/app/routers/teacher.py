"""班主任（教师）本班学生结果（问题 3）。

硬约束：教师结果对 school_admin 永远不可见；教师只能查看/导出**本人担任班主任的
班级**的学生结果。任何越权访问其他班级一律 403。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.export_service import ExportError, build_class_export, render_export
from app.models import Assessment, AssessmentStatus, Class, ScaleDef, User, UserRole
from app.schemas import TeacherClassResultOut, TeacherClassSummary
from app.security import require_role

router = APIRouter()

# 班主任可查看/导出的量表（学生量表；教师量表永不进入本班结果）。
_CLASS_SCALES = ("mht", "mssmhs")


async def _homeroom_class(db: AsyncSession, teacher: User) -> Class:
    """返回该教师担任班主任的班级；若不是班主任则 403。"""
    result = await db.execute(select(Class).where(Class.head_teacher_id == teacher.id))
    cls = result.scalars().first()
    if cls is None and teacher.is_homeroom and teacher.class_id is not None:
        cls = await db.get(Class, teacher.class_id)
    if cls is None:
        raise HTTPException(status_code=403, detail="你当前不是班主任，无法查看本班学生结果")
    return cls


def _ensure_own_class(cls: Class, class_id: int | None) -> None:
    if class_id is not None and class_id != cls.id:
        raise HTTPException(status_code=403, detail="无权访问其他班级")


async def _class_students(db: AsyncSession, cls: Class) -> list[User]:
    return (
        await db.execute(
            select(User)
            .where(User.class_id == cls.id, User.role == UserRole.STUDENT)
            .order_by(User.id)
        )
    ).scalars().all()


async def _completed_map(db: AsyncSession, student_ids: list[int], scale_id: str):
    """每个学生最近一次完成的测评（含 result）。"""
    if not student_ids:
        return {}
    assessments = (
        await db.execute(
            select(Assessment)
            .where(
                Assessment.user_id.in_(student_ids),
                Assessment.scale_id == scale_id,
                Assessment.status == AssessmentStatus.COMPLETED,
            )
            .options(selectinload(Assessment.result))
        )
    ).scalars().all()
    latest: dict[int, Assessment] = {}
    for a in assessments:
        current = latest.get(a.user_id)
        if current is None or (a.completed_at or a.started_at) >= (
            current.completed_at or current.started_at
        ):
            latest[a.user_id] = a
    return latest


@router.get("/class-summary", response_model=TeacherClassSummary)
async def class_summary(
    scale_id: str = Query("mht"),
    db: AsyncSession = Depends(get_db),
    teacher: User = Depends(require_role(UserRole.TEACHER)),
):
    if scale_id not in _CLASS_SCALES:
        raise HTTPException(status_code=400, detail="scale_id 必须是 mht 或 mssmhs")
    cls = await _homeroom_class(db, teacher)
    students = await _class_students(db, cls)
    student_ids = [s.id for s in students]
    completed_map = await _completed_map(db, student_ids, scale_id)
    total = len(students)
    completed = len(completed_map)
    return TeacherClassSummary(
        class_id=cls.id,
        class_name=cls.name,
        scale_id=scale_id,
        total=total,
        completed=completed,
        pending=max(total - completed, 0),
        completion_rate=round(completed / total, 2) if total else 0.0,
    )


async def _attempt_numbers(
    db: AsyncSession, student_ids: list[int], scale_id: str
) -> dict[int, int]:
    """每个学生在该量表上的作答序号（按开始时间，含进行中），assessment_id -> n。"""
    if not student_ids:
        return {}
    rows = (
        await db.execute(
            select(Assessment).where(
                Assessment.user_id.in_(student_ids),
                Assessment.scale_id == scale_id,
            )
        )
    ).scalars().all()
    grouped: dict[int, list[Assessment]] = {}
    for a in rows:
        grouped.setdefault(a.user_id, []).append(a)
    numbers: dict[int, int] = {}
    for group in grouped.values():
        group.sort(key=lambda a: (a.started_at or a.completed_at))
        for idx, a in enumerate(group, start=1):
            numbers[a.id] = idx
    return numbers


@router.get("/class-results", response_model=list[TeacherClassResultOut])
@router.get("/class-students-results", response_model=list[TeacherClassResultOut])
async def class_results(
    scale_id: str = Query("mht"),
    db: AsyncSession = Depends(get_db),
    teacher: User = Depends(require_role(UserRole.TEACHER)),
):
    """本班学生已完成测评的结果列表（仅本班、仅学生量表）。

    自动可见：按「本班学生 + status==COMPLETED」查询，不再依赖任何人工分发。
    教师量表结果永不出现（学生角色过滤 + 量表白名单双重保证）。
    """
    if scale_id not in _CLASS_SCALES:
        raise HTTPException(status_code=400, detail="scale_id 必须是 mht 或 mssmhs")
    cls = await _homeroom_class(db, teacher)
    students = await _class_students(db, cls)
    student_ids = [s.id for s in students]
    latest = await _completed_map(db, student_ids, scale_id)
    attempts = await _attempt_numbers(db, student_ids, scale_id)

    scale_rows = await db.execute(select(ScaleDef).where(ScaleDef.scale_id == scale_id))
    scale = scale_rows.scalar_one_or_none()
    scale_name = scale.payload.get("name", scale_id) if scale else scale_id

    reports: list[TeacherClassResultOut] = []
    for student in students:
        assessment = latest.get(student.id)
        if assessment is None:
            continue
        result = assessment.result
        completed_at = assessment.completed_at or (result.created_at if result else None)
        reports.append(
            TeacherClassResultOut(
                assessment_id=assessment.id,
                student_name=student.real_name,
                username=student.username,
                class_name=cls.name,
                gender=student.gender,
                scale_id=assessment.scale_id,
                scale_name=scale_name,
                attempt_no=attempts.get(assessment.id),
                status=assessment.status.value,
                is_valid=assessment.is_valid,
                scores=result.scores if result else {},
                risk_flags=result.risk_flags if result else [],
                llm_summary=result.llm_summary if result else None,
                fallback_used=result.fallback_used if result else False,
                completed_at=completed_at,
                created_at=completed_at,
            )
        )
    reports.sort(
        key=lambda r: (r.completed_at is not None, r.completed_at), reverse=True
    )
    return reports


@router.get("/class-export")
async def class_export(
    scale_id: str = Query("mht"),
    format: str = Query("xlsx"),
    class_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    teacher: User = Depends(require_role(UserRole.TEACHER)),
):
    """导出本班学生测评结果；请求其他班级一律 403。"""
    cls = await _homeroom_class(db, teacher)
    _ensure_own_class(cls, class_id)
    try:
        headers, rows = await build_class_export(db, cls, scale_id)
        content, media_type, disposition = render_export(cls, scale_id, format, headers, rows)
    except ExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )
