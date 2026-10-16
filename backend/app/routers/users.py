import random
import string
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models import Class, User, UserRole
from app.schemas import AccountOut, BulkResetPasswordIn
from app.security import hash_password, require_admin

router = APIRouter()

_charset = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789!@#$%&*"

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
