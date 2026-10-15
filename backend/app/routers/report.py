from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models import Assessment, AssessmentStatus, Class, Result, User, UserRole
from app.schemas import ClassReport, ReportOut
from app.security import get_current_user, require_admin, require_role

router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/classes", response_model=list[ClassReport])
async def class_reports(
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin),
):
    result = await db.execute(select(Class).options(selectinload(Class.head_teacher)))
    classes = result.scalars().all()
    out = []
    for cls in classes:
        students_result = await db.execute(
            select(User).where(User.class_id == cls.id, User.role == UserRole.STUDENT)
        )
        students = students_result.scalars().all()
        student_ids = {s.id for s in students}

        assessments_result = await db.execute(
            select(Assessment)
            .where(
                Assessment.user_id.in_(student_ids),
                Assessment.status == AssessmentStatus.COMPLETED,
                Assessment.scale_id.in_(("mht", "mssmhs")),
            )
            .options(selectinload(Assessment.result))
        )
        assessments = assessments_result.scalars().all()

        completed_count = len({a.user_id for a in assessments})
        total_count = len(students)
        completion_rate = round(completed_count / total_count, 2) if total_count else 0.0

        dim_sums: dict[str, list[float]] = defaultdict(list)
        risk_counts: dict[str, int] = defaultdict(int)

        for a in assessments:
            if not a.result or a.is_valid is False:
                continue
            scores = a.result.scores or {}
            # subscales for mht
            for key, info in (scores.get("subscales") or {}).items():
                if isinstance(info, dict) and "score" in info:
                    dim_sums[key].append(float(info["score"]))
            # factors for mssmhs / teacher_ref
            for key, info in (scores.get("factors") or {}).items():
                if isinstance(info, dict) and "mean" in info:
                    dim_sums[key].append(float(info["mean"]))
            for flag in a.result.risk_flags or []:
                risk_counts[flag.get("severity", "info")] += 1

        dim_means = {k: round(sum(v) / len(v), 2) if v else 0.0 for k, v in dim_sums.items()}

        out.append(
            ClassReport(
                class_id=cls.id,
                class_name=cls.name,
                grade_level=cls.grade_level.value,
                head_teacher_id=cls.head_teacher_id,
                head_teacher_name=cls.head_teacher.real_name if cls.head_teacher else None,
                student_count=total_count,
                completed_count=completed_count,
                completion_rate=completion_rate,
                dimension_means=dim_means,
                risk_counts=dict(risk_counts),
            )
        )
    return out


@router.post("/dispatch")
async def dispatch_results(
    class_id: int,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin),
):
    cls = await db.get(Class, class_id)
    if cls is None:
        raise HTTPException(status_code=404, detail="班级不存在")
    head_teacher_id = cls.head_teacher_id
    if head_teacher_id is None:
        # 兼容：以教师表 class_id + is_homeroom 指定的班主任为准
        homeroom_result = await db.execute(
            select(User).where(
                User.role == UserRole.TEACHER,
                User.class_id == class_id,
                User.is_homeroom.is_(True),
            )
        )
        homeroom = homeroom_result.scalars().first()
        head_teacher_id = homeroom.id if homeroom else None
    if head_teacher_id is None:
        raise HTTPException(status_code=400, detail="该班级未设置班主任")
    if cls.head_teacher_id is None:
        cls.head_teacher_id = head_teacher_id

    students_result = await db.execute(
        select(User).where(User.class_id == class_id, User.role == UserRole.STUDENT)
    )
    student_ids = {s.id for s in students_result.scalars().all()}

    assessments_result = await db.execute(
        select(Assessment).where(
            Assessment.user_id.in_(student_ids),
            Assessment.status == AssessmentStatus.COMPLETED,
        )
    )
    assessments = assessments_result.scalars().all()
    count = 0
    for a in assessments:
        a.distributed_to_teacher_id = head_teacher_id
        a.distributed_at = _now()
        count += 1
    await db.commit()
    return {"dispatched": count}


@router.get("/teacher/class-students-results", response_model=list[ReportOut])
async def teacher_class_results(
    db: AsyncSession = Depends(get_db),
    teacher=Depends(require_role(UserRole.TEACHER)),
):
    result = await db.execute(
        select(Assessment)
        .where(
            Assessment.distributed_to_teacher_id == teacher.id,
            Assessment.status == AssessmentStatus.COMPLETED,
        )
        .options(selectinload(Assessment.result), selectinload(Assessment.user))
    )
    assessments = result.scalars().all()
    reports = []
    for a in assessments:
        target = a.user
        if target and target.role == UserRole.TEACHER:
            # teacher results should never be distributed to another teacher
            continue
        reports.append(
            ReportOut(
                assessment_id=a.id,
                scale_id=a.scale_id,
                scale_name=a.scale_id,
                status=a.status.value,
                is_valid=a.is_valid,
                scores=a.result.scores if a.result else {},
                risk_flags=a.result.risk_flags if a.result else [],
                llm_summary=a.result.llm_summary if a.result else None,
                fallback_used=a.result.fallback_used if a.result else False,
                created_at=a.result.created_at if a.result else None,
            )
        )
    return reports
