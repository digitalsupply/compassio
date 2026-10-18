"""回归 docs/05 §5.1：预警通知去重改为数据库原子去重。

原缺陷：``assess._maybe_create_notification`` 先跑一次结果被丢弃的查询，紧接着再查一遍，
再「查无则插」——既冗余，又在多 worker 下有重复通知竞态。现改为唯一索引
``uq_notifications_dedup(recipient_role, title, body)`` + ``INSERT ... ON CONFLICT DO NOTHING``。
"""

from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError

import pytest

from app.models import Assessment, Notification, UserRole
from app.routers.assess import _maybe_create_notification
from tests.conftest import create_user


async def _count(db) -> int:
    return (await db.execute(select(func.count()).select_from(Notification))).scalar_one()


async def _make_assessment(db, username: str) -> Assessment:
    student = await create_user(db, UserRole.STUDENT, username)
    a = Assessment(user_id=student.id, scale_id="mht")
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


async def test_same_flag_is_not_notified_twice(db):
    a = await _make_assessment(db, "stu_notify")
    flag = {"severity": "critical", "message": "命中测试规则"}

    await _maybe_create_notification(db, a, flag)
    await _maybe_create_notification(db, a, flag)  # 同内容重复触发

    assert await _count(db) == 1
    row = (await db.execute(select(Notification))).scalar_one()
    assert row.title == "CRITICAL 预警"
    assert row.recipient_role == UserRole.SCHOOL_ADMIN


async def test_distinct_flags_are_both_notified(db):
    a = await _make_assessment(db, "stu_notify2")

    await _maybe_create_notification(db, a, {"severity": "high", "message": "规则A"})
    await _maybe_create_notification(db, a, {"severity": "high", "message": "规则B"})

    assert await _count(db) == 2


async def test_unique_index_blocks_duplicate_row(db):
    """证明原子去重是靠数据库唯一索引兜底：绕过应用直接插同内容会撞唯一键。"""
    a = await _make_assessment(db, "stu_notify3")
    await _maybe_create_notification(
        db, a, {"severity": "high", "message": "重复内容"}
    )
    row = (await db.execute(select(Notification))).scalar_one()

    with pytest.raises(IntegrityError):
        await db.execute(
            insert(Notification).values(
                recipient_role=row.recipient_role,
                severity=row.severity,
                title=row.title,
                body=row.body,
                ref_student_id=row.ref_student_id,
            )
        )
        await db.commit()
    await db.rollback()
    assert await _count(db) == 1
