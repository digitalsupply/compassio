from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Notification, UserRole
from app.schemas import NotificationOut
from app.security import get_current_user, require_admin

router = APIRouter()


@router.get("/list", response_model=list[NotificationOut])
async def list_notifications(
    unread: bool | None = Query(None),
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin),
):
    stmt = select(Notification).where(Notification.recipient_role == UserRole.SCHOOL_ADMIN)
    if unread is not None:
        stmt = stmt.where(Notification.read == (not unread))
    stmt = stmt.order_by(Notification.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/{id}/read")
async def mark_read(
    id: int,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin),
):
    notif = await db.get(Notification, id)
    if notif is None:
        raise HTTPException(status_code=404, detail="通知不存在")
    notif.read = True
    await db.commit()
    return {"ok": True}


@router.get("/unread-count")
async def unread_count(
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin),
):
    result = await db.execute(
        select(Notification).where(
            Notification.recipient_role == UserRole.SCHOOL_ADMIN,
            Notification.read == False,
        )
    )
    count = len(result.scalars().all())
    return {"count": count}
