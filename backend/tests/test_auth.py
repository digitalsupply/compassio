import time

import pytest

from app.security import create_access_token
from tests.conftest import create_user
from app.models import UserRole


async def test_login_success(client, db):
    await create_user(db, UserRole.STUDENT, "stu_auth", password="OldPass1!")
    resp = await client.post(
        "/api/auth/login", json={"username": "stu_auth", "password": "OldPass1!"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "student"
    assert "access_token" in data


async def test_login_failure(client, db):
    await create_user(db, UserRole.STUDENT, "stu_auth2", password="OldPass1!")
    resp = await client.post(
        "/api/auth/login", json={"username": "stu_auth2", "password": "wrong"}
    )
    assert resp.status_code == 401


async def test_change_password(client, db):
    await create_user(db, UserRole.STUDENT, "stu_chgpwd", password="OldPass1!")
    token_resp = await client.post(
        "/api/auth/login", json={"username": "stu_chgpwd", "password": "OldPass1!"}
    )
    token = token_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        "/api/auth/change-password",
        json={"old_password": "OldPass1!", "new_password": "NewPass2!"},
        headers=headers,
    )
    assert resp.status_code == 200

    # old password fails
    resp = await client.post(
        "/api/auth/login", json={"username": "stu_chgpwd", "password": "OldPass1!"}
    )
    assert resp.status_code == 401

    # new password works
    resp = await client.post(
        "/api/auth/login", json={"username": "stu_chgpwd", "password": "NewPass2!"}
    )
    assert resp.status_code == 200


async def test_jwt_expired(client, db):
    await create_user(db, UserRole.STUDENT, "stu_exp")
    from datetime import timedelta
    token = create_access_token({"sub": "stu_exp"}, expires_delta=timedelta(seconds=-1))
    resp = await client.get(
        "/api/assess/scales", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401
