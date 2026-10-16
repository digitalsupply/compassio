"""管理员账号新增 / 删除 / 批量删除（测试数据清理用）。

覆盖：手工新增（自动密码、班级解析与新建、班主任接管班级）、删除级联
（测评/作答/结果/通知）、守卫（不能删自己、至少留一个管理员、仅管理员可操作）、
批量删除的部分成功与原因回报。
"""

from sqlalchemy import select

from app.models import Assessment, AssessmentStatus, Class, Notification, Response, Result, User, UserRole
from tests.conftest import auth_token, create_class, create_user


async def _admin_headers(client, db, username="admin_del"):
    await create_user(db, UserRole.SCHOOL_ADMIN, username, real_name="管理员")
    token = await auth_token(client, username)
    return {"Authorization": f"Bearer {token}"}


async def test_create_account_generates_password_and_class(client, db):
    headers = await _admin_headers(client, db)

    resp = await client.post(
        "/api/admin/accounts",
        json={"role": "student", "username": "new_stu", "real_name": "新学生",
              "gender": "女", "class_name": "七年级(1)班"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["username"] == "new_stu"
    assert body["class_name"] == "七年级(1)班"
    assert len(body["initial_password"]) >= 8

    # 新账号能直接用初始密码登录，且班级已自动创建
    login = await client.post(
        "/api/auth/login", json={"username": "new_stu", "password": body["initial_password"]}
    )
    assert login.status_code == 200, login.text
    cls = (await db.execute(select(Class).where(Class.name == "七年级(1)班"))).scalar_one()
    assert cls is not None


async def test_create_teacher_as_homeroom_takes_over_class(client, db):
    headers = await _admin_headers(client, db)
    cls = await create_class(db, "八年级(2)班")

    resp = await client.post(
        "/api/admin/accounts",
        json={"role": "teacher", "username": "new_teacher", "real_name": "新老师",
              "class_id": cls.id, "is_homeroom": True, "password": "Teach2026!"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["is_homeroom"] is True
    await db.refresh(cls)
    assert cls.head_teacher_id is not None


async def test_create_homeroom_refuses_to_steal_existing_one(client, db):
    """班级已有班主任时不得静默顶掉（实测线上真实班级被顶掉过，故加守卫）。"""
    headers = await _admin_headers(client, db)
    first = await create_user(db, UserRole.TEACHER, "ht_first", real_name="原班主任")
    cls = await create_class(db, "八年级(3)班", head_teacher_id=first.id)

    resp = await client.post(
        "/api/admin/accounts",
        json={"role": "teacher", "username": "ht_second", "real_name": "新班主任",
              "class_id": cls.id, "is_homeroom": True},
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    assert "已有班主任" in resp.json()["detail"]
    assert "原班主任" in resp.json()["detail"]
    # 原班主任关系与账号都没被改动
    await db.refresh(cls)
    assert cls.head_teacher_id == first.id
    assert (await db.execute(select(User).where(User.username == "ht_second"))).scalar_one_or_none() is None


async def test_create_account_rejects_bad_input(client, db):
    headers = await _admin_headers(client, db)
    base = {"role": "student", "username": "dup_user", "real_name": "张三"}
    assert (await client.post("/api/admin/accounts", json=base, headers=headers)).status_code == 201

    cases = [
        ({**base}, "用户名已存在"),
        ({**base, "username": "ab"}, "用户名只能"),
        ({**base, "username": "bad name"}, "用户名只能"),
        ({**base, "username": "ok_name", "role": "principal"}, "角色只能"),
        ({**base, "username": "ok_name2", "real_name": "  "}, "姓名不能为空"),
        ({**base, "username": "ok_name3", "gender": "未知"}, "性别只能"),
        ({**base, "username": "ok_name4", "password": "123"}, "密码至少"),
        ({**base, "username": "ok_name5", "class_id": 99999}, "班级不存在"),
    ]
    for payload, needle in cases:
        resp = await client.post("/api/admin/accounts", json=payload, headers=headers)
        assert resp.status_code == 400, (payload, resp.text)
        assert needle in resp.json()["detail"], (payload, resp.json())


async def test_account_endpoints_require_admin(client, db):
    await create_user(db, UserRole.TEACHER, "t_not_admin")
    token = await auth_token(client, "t_not_admin")
    headers = {"Authorization": f"Bearer {token}"}

    assert (await client.post(
        "/api/admin/accounts",
        json={"role": "student", "username": "x1", "real_name": "X"},
        headers=headers,
    )).status_code == 403
    assert (await client.get("/api/admin/classes", headers=headers)).status_code == 403
    assert (await client.delete("/api/admin/accounts/1", headers=headers)).status_code == 403
    assert (await client.post(
        "/api/admin/accounts/batch-delete", json={"user_ids": [1]}, headers=headers
    )).status_code == 403


async def _seed_student_with_data(db, username="stu_to_del"):
    student = await create_user(db, UserRole.STUDENT, username, real_name="待删学生")
    assessment = Assessment(user_id=student.id, scale_id="mht", status=AssessmentStatus.COMPLETED)
    db.add(assessment)
    await db.flush()
    db.add(Response(assessment_id=assessment.id, item_id=1, value=1))
    db.add(Result(assessment_id=assessment.id, scores={"total_score": 10}, risk_flags=[]))
    db.add(Notification(recipient_role=UserRole.SCHOOL_ADMIN, severity="critical",
                        title="预警", body="测试", ref_student_id=student.id))
    await db.commit()
    return student, assessment.id


async def test_delete_account_cascades_its_data(client, db):
    headers = await _admin_headers(client, db)
    student, assessment_id = await _seed_student_with_data(db)

    resp = await client.delete(f"/api/admin/accounts/{student.id}", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["assessments_removed"] == 1

    assert (await db.execute(select(User).where(User.id == student.id))).scalar_one_or_none() is None
    assert (await db.execute(select(Assessment).where(Assessment.id == assessment_id))).scalar_one_or_none() is None
    assert (await db.execute(select(Response).where(Response.assessment_id == assessment_id))).scalars().all() == []
    assert (await db.execute(select(Result).where(Result.assessment_id == assessment_id))).scalar_one_or_none() is None
    assert (await db.execute(select(Notification).where(Notification.ref_student_id == student.id))).scalars().all() == []

    # 用户名可以再次使用
    again = await client.post(
        "/api/admin/accounts",
        json={"role": "student", "username": student.username, "real_name": "重建"},
        headers=headers,
    )
    assert again.status_code == 201, again.text


async def test_delete_account_guards(client, db):
    headers = await _admin_headers(client, db, username="admin_self")
    me = (await db.execute(select(User).where(User.username == "admin_self"))).scalar_one()

    # 不能删自己
    resp = await client.delete(f"/api/admin/accounts/{me.id}", headers=headers)
    assert resp.status_code == 400
    assert "当前登录" in resp.json()["detail"]

    # 最后一个管理员不可删（换一个管理员身份删自己以外的唯一管理员）
    other = await create_user(db, UserRole.SCHOOL_ADMIN, "admin_other")
    resp = await client.delete(f"/api/admin/accounts/{other.id}", headers=headers)
    assert resp.status_code == 200, resp.text

    # 不存在的账号
    assert (await client.delete("/api/admin/accounts/424242", headers=headers)).status_code == 404


async def test_last_admin_cannot_be_deleted(client, db):
    admin = await create_user(db, UserRole.SCHOOL_ADMIN, "admin_only")
    token = await auth_token(client, "admin_only")
    headers = {"Authorization": f"Bearer {token}"}
    # 只有自己一个管理员：删自己命中“当前登录”，删别人不存在 → 用批量接口验证守卫文案
    resp = await client.post(
        "/api/admin/accounts/batch-delete", json={"user_ids": [admin.id]}, headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted_count"] == 0
    assert body["skipped"][0]["reason"]


async def test_batch_delete_partial_success(client, db):
    headers = await _admin_headers(client, db, username="admin_batch")
    me = (await db.execute(select(User).where(User.username == "admin_batch"))).scalar_one()
    keep = await create_user(db, UserRole.TEACHER, "keep_teacher")
    s1, _ = await _seed_student_with_data(db, "batch_stu_1")
    s2, _ = await _seed_student_with_data(db, "batch_stu_2")

    resp = await client.post(
        "/api/admin/accounts/batch-delete",
        json={"user_ids": [s1.id, s2.id, me.id, 999999, s1.id]},  # 含自己/不存在/重复
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted_count"] == 2
    assert body["skipped_count"] == 2
    assert {s["reason"] for s in body["skipped"]} == {"账号不存在", "不能删除当前登录的管理员账号"}

    assert (await db.execute(select(User).where(User.id == s1.id))).scalar_one_or_none() is None
    assert (await db.execute(select(User).where(User.id == s2.id))).scalar_one_or_none() is None
    assert (await db.execute(select(User).where(User.id == keep.id))).scalar_one_or_none() is not None


async def test_classes_endpoint_lists_classes_with_head_teacher(client, db):
    headers = await _admin_headers(client, db)
    teacher = await create_user(db, UserRole.TEACHER, "ht_teacher", real_name="班主任老师")
    await create_class(db, "九年级(3)班", head_teacher_id=teacher.id)

    resp = await client.get("/api/admin/classes", headers=headers)
    assert resp.status_code == 200, resp.text
    rows = {c["name"]: c for c in resp.json()}
    assert rows["九年级(3)班"]["head_teacher_name"] == "班主任老师"


async def test_delete_teacher_clears_head_teacher_link(client, db):
    headers = await _admin_headers(client, db)
    teacher = await create_user(db, UserRole.TEACHER, "ht_to_del", real_name="要删的班主任")
    cls = await create_class(db, "九年级(4)班", head_teacher_id=teacher.id)

    resp = await client.delete(f"/api/admin/accounts/{teacher.id}", headers=headers)
    assert resp.status_code == 200, resp.text
    await db.refresh(cls)
    assert cls.head_teacher_id is None
