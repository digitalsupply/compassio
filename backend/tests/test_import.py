import pytest
from sqlalchemy import select

from app.models import Class, User, UserRole
from tests.conftest import auth_token, create_class, create_user


def _csv(header: str, *rows: str) -> dict:
    body = "\n".join([header, *rows]) + "\n"
    return {"file": ("import.csv", body.encode("utf-8"), "text/csv")}


async def _admin_headers(client, db) -> dict:
    await create_user(db, UserRole.SCHOOL_ADMIN, "admin_imp")
    token = await auth_token(client, "admin_imp")
    return {"Authorization": f"Bearer {token}"}


async def test_teacher_import_sets_class_and_homeroom(client, db):
    headers = await _admin_headers(client, db)
    files = _csv(
        "姓名,手机号,性别,班级,是否班主任",
        "张三,13800138000,男,七年级(1)班,是",
        "李四,13800138001,女,七年级(1)班,否",
    )
    resp = await client.post("/api/import/teachers/commit", files=files, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 2

    zhang = (
        await db.execute(select(User).where(User.real_name == "张三"))
    ).scalar_one()
    li = (await db.execute(select(User).where(User.real_name == "李四"))).scalar_one()
    cls = (await db.execute(select(Class).where(Class.name == "七年级(1)班"))).scalar_one()

    assert zhang.class_id == cls.id
    assert zhang.is_homeroom is True
    assert li.class_id == cls.id
    assert li.is_homeroom is False
    # 班级 ↔ 班主任 对应关系
    assert cls.head_teacher_id == zhang.id


async def test_student_import_normalizes_class_and_links_homeroom(client, db):
    headers = await _admin_headers(client, db)
    # 先导入班主任教师
    teacher_files = _csv(
        "姓名,手机号,性别,班级,是否班主任",
        "王老师,13800138002,男,七年级(2)班,是",
    )
    resp = await client.post("/api/import/teachers/commit", files=teacher_files, headers=headers)
    assert resp.status_code == 200, resp.text
    teacher = (
        await db.execute(select(User).where(User.real_name == "王老师"))
    ).scalar_one()

    # 学生用旧式 "初一(2)班" 写法、且不填班主任 → 应归一为七年级(2)班并沿用班主任
    student_files = _csv(
        "姓名,班级,性别,班主任",
        "王五,初一(2)班,男,",
        "赵六,初一(2)班,女,",
    )
    resp = await client.post("/api/import/students/commit", files=student_files, headers=headers)
    assert resp.status_code == 200, resp.text

    cls = (await db.execute(select(Class).where(Class.name == "七年级(2)班"))).scalar_one()
    assert cls.head_teacher_id == teacher.id
    wang = (await db.execute(select(User).where(User.real_name == "王五"))).scalar_one()
    assert wang.class_id == cls.id


async def test_same_name_teacher_resolved_by_class(client, db):
    headers = await _admin_headers(client, db)
    # 两个同名班主任，分属不同班级
    teacher_files = _csv(
        "姓名,手机号,性别,班级,是否班主任",
        "张伟,13800138010,男,七年级(1)班,是",
        "张伟,13800138011,男,七年级(2)班,是",
    )
    resp = await client.post("/api/import/teachers/commit", files=teacher_files, headers=headers)
    assert resp.status_code == 200, resp.text

    cls2 = (await db.execute(select(Class).where(Class.name == "七年级(2)班"))).scalar_one()
    teacher2 = (
        await db.execute(select(User).where(User.phone == "13800138011"))
    ).scalar_one()
    assert cls2.head_teacher_id == teacher2.id

    # 学生填写同名"张伟"，应按其所在班级匹配到正确的那位
    student_files = _csv(
        "姓名,班级,性别,班主任",
        "李雷,七年级(2)班,男,张伟",
    )
    resp = await client.post("/api/import/students/commit", files=student_files, headers=headers)
    assert resp.status_code == 200, resp.text
    assert cls2.head_teacher_id == teacher2.id


async def test_teacher_template_has_class_columns(client, db):
    headers = await _admin_headers(client, db)
    resp = await client.get("/api/import/template/teachers", headers=headers)
    assert resp.status_code == 200
    assert "班级" in resp.text and "是否班主任" in resp.text
