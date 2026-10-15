import pytest

from app.models import Assessment, AssessmentStatus, Result, UserRole
from tests.conftest import auth_token, create_class, create_user


async def test_student_cannot_start_teacher_ref(client, db):
    student = await create_user(db, UserRole.STUDENT, "stu_perm")
    token = await auth_token(client, "stu_perm")
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.post("/api/assess/start", json={"scale_id": "teacher_ref"}, headers=headers)
    assert resp.status_code == 403


async def test_teacher_cannot_view_other_teacher_result(client, db):
    t1 = await create_user(db, UserRole.TEACHER, "t1_perm")
    t2 = await create_user(db, UserRole.TEACHER, "t2_perm")
    a = Assessment(user_id=t2.id, scale_id="teacher_ref", status=AssessmentStatus.COMPLETED)
    db.add(a)
    await db.commit()
    await db.refresh(a)
    db.add(Result(assessment_id=a.id, scores={}, risk_flags=[]))
    await db.commit()

    token = await auth_token(client, "t1_perm")
    resp = await client.get(f"/api/assess/{a.id}/report", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code in (403, 404)


async def test_admin_cannot_view_teacher_report(client, db):
    admin = await create_user(db, UserRole.SCHOOL_ADMIN, "admin_perm")
    teacher = await create_user(db, UserRole.TEACHER, "tea_perm")
    a = Assessment(user_id=teacher.id, scale_id="teacher_ref", status=AssessmentStatus.COMPLETED)
    db.add(a)
    await db.commit()
    await db.refresh(a)
    db.add(Result(assessment_id=a.id, scores={}, risk_flags=[]))
    await db.commit()

    token = await auth_token(client, "admin_perm")
    resp = await client.get(f"/api/assess/{a.id}/report", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


async def test_admin_reports_exclude_teachers(client, db):
    admin = await create_user(db, UserRole.SCHOOL_ADMIN, "admin_rep")
    teacher = await create_user(db, UserRole.TEACHER, "tea_rep")
    a = Assessment(user_id=teacher.id, scale_id="teacher_ref", status=AssessmentStatus.COMPLETED)
    db.add(a)
    await db.commit()
    await db.refresh(a)
    db.add(Result(assessment_id=a.id, scores={}, risk_flags=[]))
    await db.commit()

    token = await auth_token(client, "admin_rep")
    resp = await client.get("/api/admin/reports/classes", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert all(r["student_count"] == 0 for r in data)
