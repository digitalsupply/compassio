import random
import string

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models import Class, User, UserRole
from app.schemas import AccountOut
from app.security import hash_password, require_admin

router = APIRouter()

_charset = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789!@#$%&*"


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
    user.must_change_password = True
    await db.commit()
    return {"username": user.username, "temporary_password": password}


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
    users = result.scalars().all()

    header = "<tr><th>姓名</th><th>用户名</th><th>角色</th><th>班级</th><th>是否班主任</th></tr>"
    body = ""
    for u in users:
        body += (
            f"<tr><td>{u.real_name}</td><td>{u.username}</td>"
            f"<td>{u.role.value}</td><td>{u.cls.name if u.cls else ''}</td>"
            f"<td>{'是' if u.is_homeroom else ''}</td></tr>"
        )
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>@media print{body{font-size:12px;} table{width:100%; border-collapse:collapse;}} "
        "table,th,td{border:1px solid #ccc; padding:6px;}</style></head>"
        "<body><h2>账号名单</h2>"
        f"<table>{header}{body}</table></body></html>"
    )
    from fastapi.responses import HTMLResponse

    return HTMLResponse(content=html)
