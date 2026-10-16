import random
import re
import string
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models import Assessment, AuditLog, Class, Notification, Response, Result, User, UserRole
from app.routers.import_ import _infer_grade_level, _normalize_class_name
from app.schemas import (
    AccountCreateIn,
    AccountCreatedOut,
    AccountDeleteResult,
    AccountOut,
    BatchDeleteIn,
    BatchDeleteResult,
    BulkResetPasswordIn,
    ClassOut,
    SkippedAccount,
)
from app.security import hash_password, require_admin

router = APIRouter()

_charset = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789!@#$%&*"

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{3,64}$")
_GENDERS = ("男", "女")

# 打印名单班内排序：教师在前，学生其次，管理员最后。
_PRINT_ROLE_ORDER = {"teacher": 0, "student": 1, "school_admin": 2}

# 批量重置密码的默认统一密码（仅管理员可触发，且不含管理员账号）。
DEFAULT_BULK_PASSWORD = "Compassio@2026"


def _gen_password(length: int = 8) -> str:
    return "".join(random.choice(_charset) for _ in range(length))


@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(
    role: str | None = Query(None),
    class_id: int | None = Query(None, alias="class"),
    q: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin),
):
    stmt = select(User).options(selectinload(User.cls))
    if role:
        stmt = stmt.where(User.role == role)
    if class_id is not None:
        stmt = stmt.where(User.class_id == class_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (User.username.ilike(like))
            | (User.real_name.ilike(like))
            | (User.phone.ilike(like))
        )
    result = await db.execute(stmt)
    users = result.scalars().all()

    out = []
    for u in users:
        out.append(
            AccountOut(
                id=u.id,
                role=u.role.value,
                username=u.username,
                real_name=u.real_name,
                gender=u.gender,
                phone=u.phone,
                class_id=u.class_id,
                class_name=u.cls.name if u.cls else None,
                is_homeroom=u.is_homeroom,
                is_active=u.is_active,
                must_change_password=u.must_change_password,
            )
        )
    return out


@router.post("/accounts/{user_id}/reset-password")
async def reset_password(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin),
):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    password = _gen_password()
    user.password_hash = hash_password(password)
    user.initial_password = password
    user.must_change_password = False
    await db.commit()
    return {"username": user.username, "temporary_password": password}


@router.post("/accounts/reset-passwords")
async def bulk_reset_passwords(
    payload: BulkResetPasswordIn,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin),
):
    """把当前筛选内的师生密码统一重置为一个密码（默认 Compassio@2026）。

    - 始终排除管理员账号（school_admin），避免把管理员自己锁在门外。
    - 重置后不强制改密（must_change_password=False），学生/教师可直接用统一密码登录。
    - 所有账号共用同一份 bcrypt 哈希（明文本就相同），避免逐个哈希拖慢 900+ 账号。
    """
    password = (payload.password or DEFAULT_BULK_PASSWORD).strip() or DEFAULT_BULK_PASSWORD
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="密码至少 8 位")

    stmt = select(User).where(User.role != UserRole.SCHOOL_ADMIN)
    if payload.role:
        stmt = stmt.where(User.role == payload.role)
    if payload.class_id is not None:
        stmt = stmt.where(User.class_id == payload.class_id)
    if payload.q:
        like = f"%{payload.q}%"
        stmt = stmt.where(
            (User.username.ilike(like))
            | (User.real_name.ilike(like))
            | (User.phone.ilike(like))
        )
    result = await db.execute(stmt)
    users = result.scalars().all()

    hashed = hash_password(password)
    for u in users:
        u.password_hash = hashed
        u.initial_password = password
        u.must_change_password = False
    await db.commit()
    return {"reset": len(users), "password": password}


@router.get("/accounts/print-roster")
async def print_roster(
    role: str | None = Query(None),
    class_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin),
):
    stmt = select(User).options(selectinload(User.cls))
    if role:
        stmt = stmt.where(User.role == role)
    if class_id is not None:
        stmt = stmt.where(User.class_id == class_id)
    result = await db.execute(stmt)
    users = list(result.scalars().all())

    # 同一班级的师生相邻：先按班级分组（无班级的账号排最后），
    # 班内教师在前、学生按姓名在后。
    users.sort(
        key=lambda u: (
            1 if u.class_id is None else 0,
            u.cls.name if u.cls else "",
            _PRINT_ROLE_ORDER.get(u.role.value, 9),
            u.real_name or "",
        )
    )

    header = "<tr><th>姓名</th><th>用户名</th><th>密码</th><th>班级</th></tr>"
    body = ""
    for u in users:
        password = u.initial_password or "已修改"
        class_name = u.cls.name if u.cls else ""
        body += (
            f"<tr><td>{escape(u.real_name or '')}</td>"
            f"<td>{escape(u.username)}</td>"
            f"<td>{escape(password)}</td>"
            f"<td>{escape(class_name)}</td></tr>"
        )
    doc = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>@media print{body{font-size:12px;} table{width:100%; border-collapse:collapse;}} "
        "table,th,td{border:1px solid #ccc; padding:6px;} .note{color:#666;font-size:12px;}</style>"
        "</head><body><h2>账号名单</h2>"
        f"<table>{header}{body}</table>"
        "<p class='note'>初始密码首次登录后需修改；已自行修改密码的显示为“已修改”。</p>"
        "</body></html>"
    )
    from fastapi.responses import HTMLResponse

    return HTMLResponse(content=doc)


# ---------------------------------------------------------------------------
# 新增 / 删除账号（管理员）
# ---------------------------------------------------------------------------


async def _audit(db: AsyncSession, actor_id: int | None, action: str, detail: dict) -> None:
    db.add(AuditLog(actor_id=actor_id, action=action, detail=detail))


async def _resolve_account_class(
    db: AsyncSession, class_id: int | None, class_name: str | None
) -> Class | None:
    """班级：优先 class_id；否则按导入同样的规范化规则找/建班级。"""
    if class_id is not None:
        cls = await db.get(Class, class_id)
        if cls is None:
            raise HTTPException(status_code=400, detail="班级不存在")
        return cls
    name = _normalize_class_name(class_name or "")
    if not name:
        return None
    result = await db.execute(select(Class).where(Class.name == name))
    cls = result.scalar_one_or_none()
    if cls is None:
        grade, _ = _infer_grade_level(name)
        cls = Class(name=name, grade_level=grade)
        db.add(cls)
        await db.flush()
    return cls


@router.get("/classes", response_model=list[ClassOut])
async def list_classes(
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin),
):
    """班级下拉用：全部班级（含班主任姓名）。"""
    result = await db.execute(
        select(Class).options(selectinload(Class.head_teacher)).order_by(Class.name)
    )
    classes = result.scalars().all()
    return [
        ClassOut(
            id=c.id,
            name=c.name,
            grade_level=c.grade_level.value if hasattr(c.grade_level, "value") else str(c.grade_level),
            head_teacher_id=c.head_teacher_id,
            head_teacher_name=c.head_teacher.real_name if c.head_teacher else None,
        )
        for c in classes
    ]


@router.post("/accounts", response_model=AccountCreatedOut, status_code=201)
async def create_account(
    payload: AccountCreateIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """新增单个账号（学生/教师/管理员），留空密码则自动生成初始密码。"""
    role = (payload.role or "").strip()
    if role not in {r.value for r in UserRole}:
        raise HTTPException(status_code=400, detail="角色只能是 school_admin / teacher / student")

    username = (payload.username or "").strip()
    if not _USERNAME_RE.match(username):
        raise HTTPException(
            status_code=400, detail="用户名只能用字母、数字、_ . @ -，长度 3–64"
        )
    exists = await db.execute(select(User).where(User.username == username))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail=f"用户名已存在：{username}")

    real_name = (payload.real_name or "").strip()
    if not real_name:
        raise HTTPException(status_code=400, detail="姓名不能为空")

    gender = (payload.gender or "").strip() or "男"
    if gender not in _GENDERS:
        raise HTTPException(status_code=400, detail="性别只能是 男 / 女")

    if payload.password is not None and payload.password != "" and len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="密码至少 8 位")
    password = (payload.password or "").strip() or _gen_password()

    # 管理员不属于任何班级
    cls = None
    is_homeroom = bool(payload.is_homeroom) and role == UserRole.TEACHER.value
    if role != UserRole.SCHOOL_ADMIN.value:
        cls = await _resolve_account_class(db, payload.class_id, payload.class_name)

    # 设为班主任前先确认该班级没有别的班主任：否则会静默顶掉既有班主任关系
    if is_homeroom and cls is not None and cls.head_teacher_id is not None:
        existing = await db.get(User, cls.head_teacher_id)
        who = f"：{existing.real_name}（{existing.username}）" if existing else ""
        raise HTTPException(
            status_code=400,
            detail=f"班级「{cls.name}」已有班主任{who}，请先取消其班主任身份或另选班级",
        )

    user = User(
        role=UserRole(role),
        username=username,
        password_hash=hash_password(password),
        initial_password=password,
        must_change_password=False,
        real_name=real_name,
        gender=gender,
        phone=(payload.phone or "").strip() or None,
        class_id=cls.id if cls is not None else None,
        is_homeroom=is_homeroom,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    # 设为班主任时接管该班级的 head_teacher_id（与导入流程一致）
    if user.is_homeroom and cls is not None:
        cls.head_teacher_id = user.id

    await _audit(
        db,
        admin.id,
        "account.create",
        {"id": user.id, "username": username, "role": role, "class": cls.name if cls else None},
    )
    await db.commit()
    await db.refresh(user)
    return AccountCreatedOut(
        id=user.id,
        role=role,
        username=user.username,
        real_name=user.real_name,
        class_name=cls.name if cls is not None else None,
        is_homeroom=user.is_homeroom,
        initial_password=password,
    )


async def _delete_account_core(db: AsyncSession, user: User, current_admin_id: int) -> int:
    """删除账号及其测评数据，返回删除的测评条数。守卫不通过时抛 400。"""
    if user.id == current_admin_id:
        raise HTTPException(status_code=400, detail="不能删除当前登录的管理员账号")
    if user.role == UserRole.SCHOOL_ADMIN:
        result = await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.role == UserRole.SCHOOL_ADMIN, User.is_active.is_(True))
        )
        if int(result.scalar_one()) <= 1:
            raise HTTPException(
                status_code=400, detail="系统至少保留一个管理员账号，无法删除最后一个管理员"
            )

    rows = await db.execute(select(Assessment.id).where(Assessment.user_id == user.id))
    assessment_ids = [r for (r,) in rows.all()]
    if assessment_ids:
        await db.execute(sa_delete(Result).where(Result.assessment_id.in_(assessment_ids)))
        await db.execute(sa_delete(Response).where(Response.assessment_id.in_(assessment_ids)))
        await db.execute(sa_delete(Assessment).where(Assessment.id.in_(assessment_ids)))

    # 其它指向该账号的引用：能置空就置空（保留业务记录），通知直接删
    await db.execute(
        sa_update(Class).where(Class.head_teacher_id == user.id).values(head_teacher_id=None)
    )
    await db.execute(
        sa_update(Assessment)
        .where(Assessment.distributed_to_teacher_id == user.id)
        .values(distributed_to_teacher_id=None)
    )
    await db.execute(sa_update(AuditLog).where(AuditLog.actor_id == user.id).values(actor_id=None))
    await db.execute(sa_delete(Notification).where(Notification.ref_student_id == user.id))
    await db.execute(sa_delete(User).where(User.id == user.id))
    return len(assessment_ids)


@router.delete("/accounts/{user_id}", response_model=AccountDeleteResult)
async def delete_account(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """删除单个账号（连同其测评/作答/结果与通知）。"""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="账号不存在")
    username, role = user.username, user.role.value
    removed = await _delete_account_core(db, user, admin.id)
    await _audit(
        db, admin.id, "account.delete", {"id": user_id, "username": username, "role": role,
                                         "assessments_removed": removed}
    )
    await db.commit()
    return AccountDeleteResult(
        id=user_id, role=role, username=username, assessments_removed=removed
    )


@router.post("/accounts/batch-delete", response_model=BatchDeleteResult)
async def batch_delete_accounts(
    payload: BatchDeleteIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """批量删除账号：逐个处理，删不掉的（自己/最后一个管理员/不存在）单独回报原因。"""
    deleted: list[AccountDeleteResult] = []
    skipped: list[SkippedAccount] = []
    for uid in dict.fromkeys(payload.user_ids or []):
        user = await db.get(User, uid)
        if user is None:
            skipped.append(SkippedAccount(id=uid, username=None, reason="账号不存在"))
            continue
        username, role = user.username, user.role.value
        try:
            removed = await _delete_account_core(db, user, admin.id)
        except HTTPException as exc:
            skipped.append(SkippedAccount(id=uid, username=username, reason=str(exc.detail)))
            continue
        deleted.append(
            AccountDeleteResult(
                id=uid, role=role, username=username, assessments_removed=removed
            )
        )
    if deleted:
        await _audit(
            db,
            admin.id,
            "account.batch_delete",
            {
                "deleted": [d.username for d in deleted],
                "skipped": [{"username": s.username, "reason": s.reason} for s in skipped],
            },
        )
    await db.commit()
    return BatchDeleteResult(
        deleted=deleted,
        skipped=skipped,
        deleted_count=len(deleted),
        skipped_count=len(skipped),
    )
