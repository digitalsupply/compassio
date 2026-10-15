import json
from pathlib import Path

import pytest

from app.engine.risk import evaluate_risks, should_notify_admin
from app.engine.scoring import score_assessment
from app.models import Assessment, Notification, Response, Result, UserRole

DATA_DIR = Path(__file__).parent.parent / "app" / "scales" / "data"


def load_scale(name: str):
    with open(DATA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


async def _make_assessment(db, user, scale_id):
    a = Assessment(user_id=user.id, scale_id=scale_id)
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


async def _answer_all(db, assessment, scale, value_map):
    for item in scale["items"]:
        val = value_map.get(item["id"], 1)
        db.add(Response(assessment_id=assessment.id, item_id=item["id"], value=val))
    await db.commit()
    await db.refresh(assessment, attribute_names=["responses"])


async def test_mht_critical_suicidal_creates_notification(client, db):
    from tests.conftest import create_user

    scale = load_scale("mht.json")
    student = await create_user(db, UserRole.STUDENT, "stu_risk1")
    a = await _make_assessment(db, student, "mht")
    # answer all non-validity 0, validity 0, except 85=1
    values = {i["id"]: 0 for i in scale["items"]}
    values[85] = 1
    await _answer_all(db, a, scale, values)

    answered = {r.item_id: r.value for r in a.responses}
    scores = score_assessment(scale, answered)
    flags = evaluate_risks(scale, answered, scores)
    assert any(f["rule_id"] == "mht-critical-suicidal-ideation" for f in flags)
    assert any(should_notify_admin(f, "mht") for f in flags)


async def test_mssmhs_critical_item_30(client, db):
    from tests.conftest import create_user

    scale = load_scale("mssmhs.json")
    student = await create_user(db, UserRole.STUDENT, "stu_risk2")
    a = await _make_assessment(db, student, "mssmhs")
    values = {i["id"]: 1 for i in scale["items"]}
    values[30] = 3
    await _answer_all(db, a, scale, values)

    answered = {r.item_id: r.value for r in a.responses}
    scores = score_assessment(scale, answered)
    flags = evaluate_risks(scale, answered, scores)
    assert any(f["rule_id"] == "mssmhs-critical-suicidal-ideation" for f in flags)


async def test_teacher_ref_does_not_create_notification(client, db):
    from tests.conftest import create_user

    scale = load_scale("teacher_ref.json")
    teacher = await create_user(db, UserRole.TEACHER, "tea_risk")
    a = await _make_assessment(db, teacher, "teacher_ref")
    # reverse raw 6 -> reversed 1; non-reverse raw 1 -> 1; low mean triggers self-care hint
    values = {i["id"]: (6 if i.get("reverse") else 1) for i in scale["items"]}
    await _answer_all(db, a, scale, values)

    answered = {r.item_id: r.value for r in a.responses}
    scores = score_assessment(scale, answered)
    flags = evaluate_risks(scale, answered, scores)
    assert len(flags) == 1
    assert flags[0]["severity"] == "self_care_hint"
    assert not should_notify_admin(flags[0], "teacher_ref")


async def test_mht_invalidity_info_flag(client, db):
    from tests.conftest import create_user

    scale = load_scale("mht.json")
    student = await create_user(db, UserRole.STUDENT, "stu_invalid")
    a = await _make_assessment(db, student, "mht")
    values = {i["id"]: 0 for i in scale["items"]}
    for iid in scale["validity_scale"]["item_ids"][:7]:
        values[iid] = 1
    await _answer_all(db, a, scale, values)

    answered = {r.item_id: r.value for r in a.responses}
    scores = score_assessment(scale, answered)
    flags = evaluate_risks(scale, answered, scores)
    assert any(f["rule_id"] == "mht-invalid-response" for f in flags)
