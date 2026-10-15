from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.engine.adaptive import pick_next_item
from app.engine.conclusion import generate_conclusion
from app.engine.risk import evaluate_risks, should_notify_admin
from app.engine.scoring import score_assessment
from app.llm.service import resolve_provider
from app.models import (
    Assessment,
    AssessmentStatus,
    Class,
    GradeLevel,
    Notification,
    NotificationSeverity,
    Response,
    Result,
    ScaleDef,
    User,
    UserRole,
)
from app.schemas import (
    AnswerRequest,
    FinishResponse,
    MyResultsOut,
    NextItem,
    ReportOut,
    ScaleBrief,
    StartAssessmentRequest,
    StartAssessmentResponse,
)
from app.security import get_current_user, require_role

router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _get_scale(db: AsyncSession, scale_id: str) -> ScaleDef:
    result = await db.execute(select(ScaleDef).where(ScaleDef.scale_id == scale_id))
    scale = result.scalar_one_or_none()
    if scale is None:
        raise HTTPException(status_code=404, detail="量表不存在")
    return scale


def _can_access_scale(user: User, scale_id: str, payload: dict) -> bool:
    audience = payload.get("audience", [])
    if user.role == UserRole.TEACHER:
        return scale_id == "teacher_ref" and "teacher" in audience
    if user.role == UserRole.STUDENT:
        if scale_id not in ("mht", "mssmhs"):
            return False
        grade = GradeLevel.JUNIOR
        if user.cls:
            grade = user.cls.grade_level
        return grade.value in audience
    return False


@router.get("/scales", response_model=list[ScaleBrief])
async def list_scales(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(ScaleDef))
    scales = result.scalars().all()
    out = []
    for s in scales:
        payload = s.payload
        if not _can_access_scale(user, s.scale_id, payload):
            continue
        out.append(
            ScaleBrief(
                scale_id=s.scale_id,
                name=payload.get("name", s.scale_id),
                version=s.version,
                audience=payload.get("audience", []),
                response_type=payload.get("response_type", ""),
                item_count=len(payload.get("items", [])),
                instruction=payload.get("instruction", ""),
                options=payload.get("options", []),
            )
        )
    return out


@router.post("/start", response_model=StartAssessmentResponse)
async def start_assessment(
    req: StartAssessmentRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    scale = await _get_scale(db, req.scale_id)
    if not _can_access_scale(user, req.scale_id, scale.payload):
        raise HTTPException(status_code=403, detail="无权使用该量表")
    assessment = Assessment(user_id=user.id, scale_id=req.scale_id, started_at=_now())
    db.add(assessment)
    await db.flush()
    await db.refresh(assessment)
    return StartAssessmentResponse(
        assessment_id=assessment.id,
        scale_id=assessment.scale_id,
        status=assessment.status.value,
    )


async def _load_assessment(db: AsyncSession, assessment_id: int, user: User) -> Assessment:
    result = await db.execute(
        select(Assessment)
        .where(Assessment.id == assessment_id)
        .options(selectinload(Assessment.responses))
    )
    assessment = result.scalar_one_or_none()
    if assessment is None:
        raise HTTPException(status_code=404, detail="测评不存在")
    if assessment.user_id != user.id and user.role != UserRole.SCHOOL_ADMIN:
        raise HTTPException(status_code=403, detail="无权访问该测评")
    return assessment


@router.get("/{id}/next", response_model=NextItem)
async def get_next_item(
    id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    assessment = await _load_assessment(db, id, user)
    if assessment.status == AssessmentStatus.COMPLETED:
        return NextItem(
            assessment_id=id, item_id=None, text=None, transition=None,
            progress={"answered": len(assessment.responses), "total": len(assessment.responses)},
            finished=True,
        )
    scale = await _get_scale(db, assessment.scale_id)
    answered = {r.item_id: r.value for r in assessment.responses}
    provider = await resolve_provider(db)
    chosen, transition, fallback = await pick_next_item(scale.payload, answered, provider)

    if chosen is not None and chosen not in assessment.item_order:
        assessment.item_order.append(chosen)
        await db.commit()

    item_text = None
    if chosen is not None:
        for it in scale.payload["items"]:
            if it["id"] == chosen:
                item_text = it["text"]
                break

    total = len(scale.payload["items"])
    finished = chosen is None
    return NextItem(
        assessment_id=id,
        item_id=chosen,
        text=item_text,
        transition=transition,
        progress={"answered": len(answered), "total": total},
        finished=finished,
    )


@router.post("/{id}/answer")
async def submit_answer(
    id: int,
    req: AnswerRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    assessment = await _load_assessment(db, id, user)
    if assessment.status == AssessmentStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="测评已完成")
    scale = await _get_scale(db, assessment.scale_id)
    payload = scale.payload
    item_ids = {i["id"] for i in payload["items"]}
    if req.item_id not in item_ids:
        raise HTTPException(status_code=400, detail="题号无效")
    allowed = {o["value"] for o in payload["options"]}
    if req.value not in allowed:
        raise HTTPException(status_code=400, detail="选项值无效")

    # upsert response
    result = await db.execute(
        select(Response).where(
            Response.assessment_id == id, Response.item_id == req.item_id
        )
    )
    resp = result.scalar_one_or_none()
    if resp is None:
        resp = Response(
            assessment_id=id, item_id=req.item_id, value=req.value, answered_at=_now()
        )
        db.add(resp)
    else:
        resp.value = req.value
        resp.answered_at = _now()
    await db.commit()

    # refresh responses for risk eval
    await db.refresh(assessment, attribute_names=["responses"])
    answered = {r.item_id: r.value for r in assessment.responses}
    scores = score_assessment(payload, answered)
    flags = evaluate_risks(payload, answered, scores)

    for flag in flags:
        if should_notify_admin(flag, assessment.scale_id):
            await _maybe_create_notification(db, assessment, flag)

    return {"ok": True, "risk_flags": flags}


async def _maybe_create_notification(
    db: AsyncSession, assessment: Assessment, flag: dict
):
    user = await db.get(User, assessment.user_id)
    title = f"{flag['severity'].upper()} 预警"
    body = (
        f"学生 {user.real_name if user else ''}（班级：{user.cls.name if user and user.cls else '-'}）"
        f"在量表 {assessment.scale_id} 命中规则：{flag['message']}"
    )
    await db.execute(
        select(Notification).where(
            Notification.recipient_role == UserRole.SCHOOL_ADMIN,
            Notification.title == title,
            Notification.body == body,
        )
    )
    # naive dedup check
    existing = await db.execute(
        select(Notification).where(
            Notification.recipient_role == UserRole.SCHOOL_ADMIN,
            Notification.title == title,
            Notification.body == body,
        )
    )
    if existing.scalar_one_or_none() is None:
        db.add(
            Notification(
                recipient_role=UserRole.SCHOOL_ADMIN,
                severity=NotificationSeverity(flag["severity"])
                if flag["severity"] in ("info", "high", "critical")
                else NotificationSeverity.INFO,
                title=title,
                body=body,
                ref_student_id=assessment.user_id,
            )
        )
        await db.commit()


@router.post("/{id}/finish", response_model=FinishResponse)
async def finish_assessment(
    id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    assessment = await _load_assessment(db, id, user)
    if assessment.status == AssessmentStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="测评已完成")
    scale = await _get_scale(db, assessment.scale_id)
    payload = scale.payload
    answered = {r.item_id: r.value for r in assessment.responses}
    total_items = len(payload["items"])
    if len(answered) < total_items:
        raise HTTPException(
            status_code=400,
            detail=f"还有 {total_items - len(answered)} 题未答完",
        )

    scores = score_assessment(payload, answered)
    flags = evaluate_risks(payload, answered, scores)

    is_valid = scores.get("is_valid", True)
    invalid_reason = None
    if not is_valid:
        invalid_reason = payload.get("validity_scale", {}).get(
            "note", "效度量表得分过高，结果仅供参考"
        )

    provider = await resolve_provider(db)
    summary, fallback_used = await generate_conclusion(payload, scores, flags, provider)

    result = Result(
        assessment_id=id,
        scores=scores,
        risk_flags=flags,
        llm_summary=summary,
        fallback_used=fallback_used,
    )
    db.add(result)
    assessment.status = AssessmentStatus.COMPLETED
    assessment.completed_at = _now()
    assessment.is_valid = is_valid
    assessment.invalidated_reason = invalid_reason
    await db.commit()
    await db.refresh(result)

    return FinishResponse(
        assessment_id=id,
        status=assessment.status.value,
        is_valid=is_valid,
        result_id=result.id,
    )


@router.get("/my-results", response_model=MyResultsOut)
async def my_results(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Returns results belonging to the current user only."""
    result = await db.execute(
        select(Assessment)
        .where(Assessment.user_id == user.id, Assessment.status == AssessmentStatus.COMPLETED)
        .options(selectinload(Assessment.result), selectinload(Assessment.user))
    )
    assessments = result.scalars().all()
    reports = [_report_from_assessment(a, current_user=user) for a in assessments]
    return MyResultsOut(results=reports)


@router.get("/{id}/report", response_model=ReportOut)
async def get_report(
    id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    assessment = await _load_assessment(db, id, user)
    if user.role == UserRole.TEACHER:
        # teacher can only see own reports
        if assessment.user_id != user.id:
            raise HTTPException(status_code=403, detail="无权查看他人报告")
    elif user.role == UserRole.SCHOOL_ADMIN:
        # admin must never see teacher reports; only student reports
        if assessment.user_id != user.id:
            target = await db.get(User, assessment.user_id)
            if target is None or target.role != UserRole.STUDENT:
                raise HTTPException(status_code=403, detail="无权查看该报告")
    # students: _load_assessment already enforces ownership
    return _report_from_assessment(assessment, current_user=user)


def _report_from_assessment(assessment: Assessment, current_user: User) -> ReportOut:
    scale_name = ""
    # load scale name from payload? We don't have payload here; use scale_id
    return ReportOut(
        assessment_id=assessment.id,
        scale_id=assessment.scale_id,
        scale_name=assessment.scale_id,
        status=assessment.status.value,
        is_valid=assessment.is_valid,
        scores=assessment.result.scores if assessment.result else {},
        risk_flags=assessment.result.risk_flags if assessment.result else [],
        llm_summary=assessment.result.llm_summary if assessment.result else None,
        fallback_used=assessment.result.fallback_used if assessment.result else False,
        created_at=assessment.result.created_at if assessment.result else None,
    )
