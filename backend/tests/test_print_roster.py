import pytest

from app.models import UserRole
from tests.conftest import auth_token, create_class, create_user


async def _set_initial_password(db, user, password):
    user.initial_password = password
    await db.commit()
    return user


@pytest.mark.asyncio
async def test_print_roster_columns_grouping_and_password(client, db):
    await create_user(db, UserRole.SCHOOL_ADMIN, "admin1", real_name="管理员")

    cls1 = await create_class(db, "七年级(1)班")
    cls2 = await create_class(db, "七年级(2)班")

    t1 = await create_user(db, UserRole.TEACHER, "t_zhang", real_name="张老师", class_id=cls1.id)
    s1 = await create_user(db, UserRole.STUDENT, "s_li", real_name="李明", class_id=cls1.id)
    t2 = await create_user(db, UserRole.TEACHER, "t_zhao", real_name="赵老师", class_id=cls2.id)
    s2 = await create_user(db, UserRole.STUDENT, "s_wang", real_name="王芳", class_id=cls2.id)
    # 无班级账号（管理员）应排在最后
    anon = await create_user(db, UserRole.TEACHER, "t_anon", real_name="独立老师")

    await _set_initial_password(db, t1, "PassA1!")
    await _set_initial_password(db, s1, "PassB2!")
    await _set_initial_password(db, s2, "PassD4!")
    # t2 / anon 保持 initial_password=None

    token = await auth_token(client, "admin1")
    resp = await client.get(
        "/api/admin/accounts/print-roster",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    text = resp.text

    # 表头：有“密码”，不再有“角色/是否班主任”
    assert "密码" in text
    assert "角色" not in text
    assert "是否班主任" not in text

    # 明文初始密码与已修改占位
    assert "PassA1!" in text
    assert "PassB2!" in text
    assert "PassD4!" in text
    assert "已修改" in text

    # 同一班级师生相邻：班内教师在前、学生其次；无班级排最后
    order = [
        text.index("t_zhang"),
        text.index("s_li"),
        text.index("t_zhao"),
        text.index("s_wang"),
        text.index("t_anon"),
    ]
    assert order == sorted(order), order
    assert t2.initial_password is None and anon.initial_password is None


@pytest.mark.asyncio
async def test_print_roster_after_reset_and_self_change(client, db):
    await create_user(db, UserRole.SCHOOL_ADMIN, "admin2", real_name="管理员")
    student = await create_user(db, UserRole.STUDENT, "s_reset", real_name="重置生")

    token = await auth_token(client, "admin2")
    headers = {"Authorization": f"Bearer {token}"}

    # 重置密码 → 应写入 initial_password，名单可见
    reset = await client.post(
        f"/api/admin/accounts/{student.id}/reset-password", headers=headers
    )
    assert reset.status_code == 200, reset.text
    temp = reset.json()["temporary_password"]

    roster = await client.get("/api/admin/accounts/print-roster", headers=headers)
    assert temp in roster.text

    # 本人自助改密 → 清空 initial_password，名单显示“已修改”
    login = await client.post(
        "/api/auth/login", json={"username": "s_reset", "password": temp}
    )
    assert login.status_code == 200, login.text
    stu_token = login.json()["access_token"]
    changed = await client.post(
        "/api/auth/change-password",
        json={"old_password": temp, "new_password": "NewPass9!"},
        headers={"Authorization": f"Bearer {stu_token}"},
    )
    assert changed.status_code == 200, changed.text

    await db.refresh(student)
    assert student.initial_password is None
    roster2 = await client.get("/api/admin/accounts/print-roster", headers=headers)
    assert "已修改" in roster2.text


@pytest.mark.asyncio
async def test_bulk_reset_passwords_scope_and_admin_exclusion(client, db):
    admin = await create_user(db, UserRole.SCHOOL_ADMIN, "admin3", real_name="管理员")
    other_admin = await create_user(db, UserRole.SCHOOL_ADMIN, "admin4", real_name="管理员2")
    cls1 = await create_class(db, "八年级(1)班")
    cls2 = await create_class(db, "八年级(2)班")
    s1 = await create_user(db, UserRole.STUDENT, "s_a", real_name="甲", class_id=cls1.id)
    t1 = await create_user(db, UserRole.TEACHER, "t_a", real_name="乙", class_id=cls1.id)
    s2 = await create_user(db, UserRole.STUDENT, "s_b", real_name="丙", class_id=cls2.id)

    token = await auth_token(client, "admin3")
    headers = {"Authorization": f"Bearer {token}"}

    # 仅重置 cls1 的师生
    res = await client.post(
        "/api/admin/accounts/reset-passwords",
        json={"class_id": cls1.id, "password": "School@123"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"reset": 2, "password": "School@123"}

    for u in (s1, t1):
        await db.refresh(u)
        assert u.initial_password == "School@123"
        assert u.must_change_password is False
    await db.refresh(s2)
    assert s2.initial_password is None
    # 管理员账号始终不被批量重置
    for a in (admin, other_admin):
        await db.refresh(a)
        assert a.initial_password is None

    roster = await client.get("/api/admin/accounts/print-roster", headers=headers)
    assert "School@123" in roster.text

    # 无筛选时只重置师生（3 个），仍排除管理员
    res2 = await client.post(
        "/api/admin/accounts/reset-passwords",
        json={"password": "School@999"},
        headers=headers,
    )
    assert res2.json()["reset"] == 3

    # 密码过短被拒
    bad = await client.post(
        "/api/admin/accounts/reset-passwords",
        json={"password": "short"},
        headers=headers,
    )
    assert bad.status_code == 400
