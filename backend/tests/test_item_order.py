"""回归 docs/05 §5.1：``assessment.item_order`` 的原地 append 必须真正落库。

原缺陷：该列是裸 ``JSON``，SQLAlchemy 不追踪原地变更，于是
``assessment.item_order.append(...)`` 之后 commit 不产生 UPDATE，读回仍是旧值
（审查里实测 append 后仍是 ``[]``）。改用 ``MutableList.as_mutable(JsonType)`` 修复。
"""

from sqlalchemy import select

from app.models import Assessment, AssessmentStatus, UserRole
from tests.conftest import create_user


async def test_item_order_append_persists(db):
    student = await create_user(db, UserRole.STUDENT, "stu_order")
    a = Assessment(
        user_id=student.id, scale_id="mht", status=AssessmentStatus.IN_PROGRESS
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    assert a.item_order == []

    # 复刻 assess.py 的写法：取到对象后原地 append，再 commit
    a.item_order.append("q1")
    a.item_order.append("q2")
    await db.commit()

    # 直接按列查库，绕开 identity map，确认真的写进去了
    persisted = (
        await db.execute(select(Assessment.item_order).where(Assessment.id == a.id))
    ).scalar_one()
    assert persisted == ["q1", "q2"]
