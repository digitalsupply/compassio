import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import ScaleDef
from app.schemas import ScaleDefOut
from app.security import require_admin

router = APIRouter()


@router.get("", response_model=list[ScaleDefOut])
async def list_scales(
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin),
):
    result = await db.execute(select(ScaleDef))
    scales = result.scalars().all()
    return [
        ScaleDefOut(
            scale_id=s.scale_id,
            version=s.version,
            loaded_at=s.loaded_at,
            item_count=len(s.payload.get("items", [])),
        )
        for s in scales
    ]


@router.post("/{scale_id}/reload")
async def reload_scale(
    scale_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin),
):
    try:
        payload = json.loads(await file.read())
    except Exception:
        raise HTTPException(status_code=400, detail="JSON 解析失败")

    if payload.get("id") != scale_id:
        raise HTTPException(status_code=400, detail="文件中的 scale_id 与路径不一致")

    result = await db.execute(select(ScaleDef).where(ScaleDef.scale_id == scale_id))
    scale = result.scalar_one_or_none()
    if scale is None:
        raise HTTPException(status_code=404, detail="量表不存在")

    scale.payload = payload
    scale.version = payload.get("version", scale.version)
    await db.commit()
    return {"scale_id": scale_id, "version": scale.version}
