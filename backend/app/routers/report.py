from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.export_service import ExportError, build_class_export, render_export
from app.models import Assessment, AssessmentStatus, Class, User, UserRole
from app.schemas import ClassReport
from app.security import require_admin

router = APIRouter()

# 班级报告可统计的学生量表；教师量表（teacher_ref）永不进入统计。
_CLASS_REPORT_SCALES = ("mht", "mssmhs")
# 允许的统计口径：all（合并，向后兼容）+ 单一量表。
_CLASS_REPORT_SCALE_CHOICES = ("all",) + _CLASS_REPORT_SCALES


@router.get("/classes", response_model=list[ClassReport])
async def class_reports(
    scale_id: str = Query("all"),
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin),
):
    """班级完成人数/完成率/维度均值统计。

    `scale_id` 决定统计口径，与导出 `GET /reports/export?scale_id=` 对齐：
    - `mht` / `mssmhs`：只统计该量表（与导出文件同一口径）；
    - `all`（默认，向后兼容）：合并 mht + mssmhs（任一量表完成即算完成）。
    非法值一律 400。
    """
    if scale_id not in _CLASS_REPORT_SCALE_CHOICES:
        raise HTTPException(status_code=400, detail="scale_id 必须是 all、mht 或 mssmhs")

    scale_filter = (
        Assessment.scale_id.in_(_CLASS_REPORT_SCALES)
        if scale_id == "all"
        else Assessment.scale_id == scale_id
    )

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
                scale_filter,
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
                total=total_count,
                completed=completed_count,
                pending=max(total_count - completed_count, 0),
            )
        )
    return out


@router.get("/export")
async def export_class_report(
    class_id: int = Query(...),
    scale_id: str = Query("mht"),
    format: str = Query("xlsx"),
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin),
):
    """按班级导出学生测评结果（问题 3）。

    仅 school_admin 可调用；导出仅包含学生，绝不包含任何教师量表数据。
    未完成的学生同样出现在表里（状态=未完成，分数列留空）。
    """
    cls = await db.get(Class, class_id)
    if cls is None:
        raise HTTPException(status_code=404, detail="班级不存在")
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


# NOTE: POST /dispatch (manual result distribution) and the distributed-only
# GET /teacher/class-students-results were removed. Teacher visibility is now
# automatic (see app/routers/teacher.py::class_results); the legacy
# Assessment.distributed_to_teacher_id / distributed_at columns are deprecated.
