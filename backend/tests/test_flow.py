import pytest

from app.models import AssessmentStatus, UserRole
from tests.conftest import auth_token, create_class, create_user


async def test_complete_mht_and_report(client, db):
    cls = await create_class(db, "八年级(2)班")
    student = await create_user(db, UserRole.STUDENT, "stu_flow", class_id=cls.id)
    token = await auth_token(client, "stu_flow")
    headers = {"Authorization": f"Bearer {token}"}

    start = await client.post("/api/assess/start", json={"scale_id": "mht"}, headers=headers)
    assert start.status_code == 200
    aid = start.json()["assessment_id"]

    asked = set()
    for _ in range(110):
        nxt = await client.get(f"/api/assess/{aid}/next", headers=headers)
        data = nxt.json()
        if data["finished"]:
            break
        await client.post(
            f"/api/assess/{aid}/answer",
            json={"item_id": data["item_id"], "value": 0},
            headers=headers,
        )
        asked.add(data["item_id"])

    assert len(asked) == 100
    finish = await client.post(f"/api/assess/{aid}/finish", headers=headers)
    assert finish.status_code == 200
    assert finish.json()["is_valid"] is True

    report = await client.get(f"/api/assess/{aid}/report", headers=headers)
    assert report.status_code == 200
    data = report.json()
    assert data["scale_id"] == "mht"
    assert "scores" in data

    my_results = await client.get("/api/assess/my-results", headers=headers)
    assert my_results.status_code == 200
    assert len(my_results.json()["results"]) == 1


async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "db" in data
    assert data["db"] is True
