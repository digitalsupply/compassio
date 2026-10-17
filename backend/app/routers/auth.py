from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import Class, User
from app.ratelimit import clear_login_failures, is_login_locked, record_login_failure
from app.schemas import ChangePasswordRequest, LoginRequest, Token
from app.security import create_access_token, get_current_user, hash_password, verify_password

router = APIRouter()


@router.post("/login", response_model=Token)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    # 爆破防护：同一用户名失败次数超限后直接 429，且在锁定期间即使用对密码也拒绝，
    # 避免攻击者用“是否 200”判定密码正确性。
    if await is_login_locked(payload.username):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登录失败次数过多，请稍后再试",
            headers={
                "Retry-After": str(get_settings().login_rate_limit_window_seconds)
            },
        )

    result = await db.execute(select(User).where(User.username == payload.username))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(
        payload.password, user.password_hash
    ):
        await record_login_failure(payload.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    await clear_login_failures(payload.username)
    token = create_access_token(
        data={"sub": user.username, "role": user.role},
        expires_delta=timedelta(minutes=get_settings().access_token_expire_minutes),
    )
    return Token(
        access_token=token,
        role=user.role,
        must_change_password=user.must_change_password,
    )


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="旧密码不正确")
    user.password_hash = hash_password(payload.new_password)
    user.initial_password = None  # 已自行改密，名单不再显示初始密码
    user.must_change_password = False
    await db.commit()
    return {"ok": True}

@router.get("/me")
async def me(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """当前登录用户的基本信息（本人可见；不返回任何他人数据）。"""
    class_name = None
    if user.class_id is not None:
        cls = await db.get(Class, user.class_id)
        class_name = cls.name if cls else None
    return {
        "id": user.id,
        "username": user.username,
        "real_name": user.real_name,
        "gender": user.gender or "",
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "class_name": class_name,
        "is_homeroom": bool(getattr(user, "is_homeroom", False)),
    }
