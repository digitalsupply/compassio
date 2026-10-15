from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import get_db
from app.engine.adaptive import pick_next_item
from app.engine.conclusion import generate_conclusion
from app.engine.risk import evaluate_risks, should_notify_admin
from app.engine.scoring import score_assessment
from app.llm.service import resolve_provider
from app.next_cache import read_next, schedule_prefetch
from app.observability.metrics import (
    assessments_completed_total,
    assessments_started_total,
    inc_next_cache,
    items_answered_total,
    risk_flags_total,
)
from app.observability.tracing import set_span_attributes, start_span
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
    StudentBrief,
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

    # 一次性取回该用户的全部测评，按量表聚合完成/进行中状态（问题 2）。
    assessments = (
        await db.execute(
            select(Assessment).where(Assessment.user_id == user.id)
        )
    ).scalars().all()
    stats: dict[str, dict[str, Any]] = {}
    for a in assessments:
        entry = stats.setdefault(
            a.scale_id,
            {"attempts": 0, "completed_at": None, "in_progress": False},
        )
        if a.status == AssessmentStatus.COMPLETED:
            entry["attempts"] += 1
            completed = a.completed_at
            previous = entry["completed_at"]
            if completed is not None and (
                previous is None or completed > previous
            ):
                entry["completed_at"] = completed
        elif a.status == AssessmentStatus.IN_PROGRESS:
            entry["in_progress"] = True

    out = []
    for s in scales:
        payload = s.payload
        if not _can_access_scale(user, s.scale_id, payload):
            continue
        entry = stats.get(s.scale_id, {})
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
                completed=entry.get("attempts", 0) > 0,
                completed_at=entry.get("completed_at"),
                attempts=entry.get("attempts", 0),
                in_progress=entry.get("in_progress", False),
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
    # 断点续答：同一量表已有进行中的测评则直接复用，避免重复开测
    existing = (
        await db.execute(
            select(Assessment).where(
                Assessment.user_id == user.id,
                Assessment.scale_id == req.scale_id,
                Assessment.status == AssessmentStatus.IN_PROGRESS,
            )
        )
    ).scalars().first()
    if existing is not None:
        schedule_prefetch(existing.id)
        return StartAssessmentResponse(
            assessment_id=existing.id,
            scale_id=existing.scale_id,
            status=existing.status.value,
        )
    assessment = Assessment(user_id=user.id, scale_id=req.scale_id, started_at=_now())
    db.add(assessment)
    await db.commit()
    await db.refresh(assessment)
    assessments_started_total.labels(assessment.scale_id).inc()
    schedule_prefetch(assessment.id)
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
            source="finished",
            mode=get_settings().adaptive_strategy,
        )
    scale = await _get_scale(db, assessment.scale_id)
    answered = {r.item_id: r.value for r in assessment.responses}

    # Fast path: consume a prefetched next item if present and still valid.
    chosen = transition = source = None
    used_cache = False
    cached = await read_next(id)
    if cached is not None:
        cached_item = cached.get("item_id")
        if cached_item is None or cached_item not in answered:
            chosen = cached_item
            transition = cached.get("transition")
            source = cached.get("source")
            used_cache = True
        # else: stale entry -> fall through to recompute

    if not used_cache:
        provider = await resolve_provider(db)
        chosen, transition, fallback, source = await pick_next_item(
            scale.payload,
            answered,
            provider,
            assessment_id=id,
            # 前台 /next 才统计 LLM 等待；预取走默认 False。
            observe_llm_wait=True,
        )
        # cache miss 的归因：只有真的落到 LLM 检查点才叫 llm_blocked，
        # 其余（覆盖阶段/规则加权/未配置 provider）是正常的规则兜底。
        # 全部答完（finished）不算预取未命中，避免污染命中率分母。
        if source != "finished":
            if source in ("llm_fusion", "llm", "rule_fallback"):
                inc_next_cache("miss", reason="llm_blocked")
            else:
                inc_next_cache("miss", reason="no_prefetch")

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
        source=source,
        mode=get_settings().adaptive_strategy,
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

    items_answered_total.labels(assessment.scale_id).inc()
    schedule_prefetch(id)
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

    scale_id = assessment.scale_id
    finish_started = perf_counter()
    span = start_span("assess.finish", {"scale": scale_id, "stage": "finish"})
    with span as active:
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

        assessments_completed_total.labels(scale_id).inc()
        for flag in flags:
            risk_flags_total.labels(scale_id, str(flag.get("severity", "unknown"))).inc()
        set_span_attributes(
            active,
            {
                "scale": scale_id,
                "stage": "finish",
                "outcome": "ok",
                "fallback": fallback_used,
                "duration_ms": round((perf_counter() - finish_started) * 1000, 3),
            },
        )

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
    """Returns all attempts (completed + in-progress) belonging to the current user."""
    result = await db.execute(
        select(Assessment)
        .where(Assessment.user_id == user.id)
        .options(selectinload(Assessment.result), selectinload(Assessment.user))
    )
    assessments = result.scalars().all()

    scale_rows = await db.execute(select(ScaleDef))
    scale_names = {
        s.scale_id: s.payload.get("name", s.scale_id) for s in scale_rows.scalars().all()
    }

    # 同一量表按时间排序编号（第 1 次、第 2 次…），进行中的也占一个序号。
    by_scale: dict[str, list[Assessment]] = {}
    for a in assessments:
        by_scale.setdefault(a.scale_id, []).append(a)
    attempt_no: dict[int, int] = {}
    for group in by_scale.values():
        for idx, a in enumerate(sorted(group, key=lambda x: x.started_at or x.completed_at), start=1):
            attempt_no[a.id] = idx

    reports = [
        _report_from_assessment(
            a,
            scale_name=scale_names.get(a.scale_id, a.scale_id),
            attempt_no=attempt_no.get(a.id),
        )
        for a in assessments
    ]
    reports.sort(key=lambda r: (r.created_at is not None, r.created_at), reverse=True)

    # 当前登录学生本人的信息（只返回自己，供报告页与打印件展示）。
    class_name = None
    if user.class_id is not None:
        cls = await db.get(Class, user.class_id)
        class_name = cls.name if cls else None
    student = StudentBrief(
        id=user.id,
        real_name=user.real_name,
        username=user.username,
        gender=user.gender or "",
        class_name=class_name,
    )
    return MyResultsOut(student=student, results=reports)


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
    scale = await _get_scale(db, assessment.scale_id)
    return _report_from_assessment(
        assessment, current_user=user, scale_name=scale.payload.get("name", assessment.scale_id)
    )


def _report_from_assessment(
    assessment: Assessment,
    current_user: User | None = None,
    scale_name: str | None = None,
    attempt_no: int | None = None,
) -> ReportOut:
    if assessment.status == AssessmentStatus.COMPLETED:
        created_at = assessment.result.created_at if assessment.result else None
    else:
        created_at = assessment.started_at
    return ReportOut(
        assessment_id=assessment.id,
        scale_id=assessment.scale_id,
        scale_name=scale_name or assessment.scale_id,
        status=assessment.status.value,
        is_valid=assessment.is_valid,
        scores=assessment.result.scores if assessment.result else {},
        risk_flags=assessment.result.risk_flags if assessment.result else [],
        llm_summary=assessment.result.llm_summary if assessment.result else None,
        fallback_used=assessment.result.fallback_used if assessment.result else False,
        created_at=created_at,
        attempt_no=attempt_no,
    )
