import json
from pathlib import Path

import pytest

from app.engine.scoring import score_assessment

DATA_DIR = Path(__file__).parent.parent / "app" / "scales" / "data"


def load_scale(name: str):
    with open(DATA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def test_mht_all_yes_invalid():
    scale = load_scale("mht.json")
    answers = {i["id"]: 1 for i in scale["items"]}
    scores = score_assessment(scale, answers)
    assert scores["is_valid"] is False
    assert scores["validity_score"] == 10
    assert scores["total_score"] == 90
    assert scores["total_level"] == "high"


def test_mht_validity_boundary():
    scale = load_scale("mht.json")
    validity_ids = scale["validity_scale"]["item_ids"]
    # answer non-validity normally 0; set exactly 6 validity items to 1
    answers = {i["id"]: 0 for i in scale["items"]}
    for iid in validity_ids[:6]:
        answers[iid] = 1
    scores = score_assessment(scale, answers)
    assert scores["validity_score"] == 6
    assert scores["is_valid"] is True

    answers[validity_ids[6]] = 1
    scores = score_assessment(scale, answers)
    assert scores["validity_score"] == 7
    assert scores["is_valid"] is False


def test_mht_total_bands():
    scale = load_scale("mht.json")
    non_validity = [i["id"] for i in scale["items"] if i["id"] not in set(scale["validity_scale"]["item_ids"])]
    # total 55 normal
    yes_ids = non_validity[:55]
    answers = {i["id"]: (1 if i["id"] in yes_ids else 0) for i in scale["items"]}
    answers.update({i["id"]: 0 for i in scale["items"] if i["id"] in scale["validity_scale"]["item_ids"]})
    scores = score_assessment(scale, answers)
    assert scores["total_score"] == 55
    assert scores["total_level"] == "normal"

    # 56 subthreshold
    answers[non_validity[55]] = 1
    scores = score_assessment(scale, answers)
    assert scores["total_score"] == 56
    assert scores["total_level"] == "subthreshold"

    # 65 high
    for iid in non_validity[56:65]:
        answers[iid] = 1
    scores = score_assessment(scale, answers)
    assert scores["total_score"] == 65
    assert scores["total_level"] == "high"


def test_mht_subscale_concern():
    scale = load_scale("mht.json")
    la = [i["id"] for i in scale["items"] if i.get("subscale") == "learning_anxiety"]
    answers = {i["id"]: 0 for i in scale["items"]}
    for iid in la[:8]:
        answers[iid] = 1
    answers.update({i["id"]: 0 for i in scale["items"] if i["id"] in scale["validity_scale"]["item_ids"]})
    scores = score_assessment(scale, answers)
    assert scores["subscales"]["learning_anxiety"]["score"] == 8
    assert "learning_anxiety" in scores["subscale_concerns"]


def test_mssmhs_all_high():
    scale = load_scale("mssmhs.json")
    answers = {i["id"]: 5 for i in scale["items"]}
    scores = score_assessment(scale, answers)
    assert scores["total_mean"] == 5.0
    assert scores["overall_level"] == "overall_issue"
    for info in scores["factor_bands"].values():
        assert info["level"] == "moderate_plus"


def test_mssmhs_factor_bands():
    scale = load_scale("mssmhs.json")
    ocd = [i["id"] for i in scale["items"] if i.get("subscale") == "ocd"]
    answers = {i["id"]: 1 for i in scale["items"]}
    for iid in ocd:
        answers[iid] = 2
    scores = score_assessment(scale, answers)
    assert scores["factors"]["ocd"]["mean"] == 2.0
    assert scores["factor_bands"]["ocd"]["level"] == "mild"


def test_mssmhs_boundary_moderate():
    scale = load_scale("mssmhs.json")
    ocd = [i["id"] for i in scale["items"] if i.get("subscale") == "ocd"]
    answers = {i["id"]: 1 for i in scale["items"]}
    for iid in ocd:
        answers[iid] = 3
    scores = score_assessment(scale, answers)
    assert scores["factors"]["ocd"]["mean"] == 3.0
    assert scores["factor_bands"]["ocd"]["level"] == "moderate_plus"


def test_teacher_ref_reverse_scoring():
    scale = load_scale("teacher_ref.json")
    item2 = next(i for i in scale["items"] if i["id"] == 2)
    assert item2["reverse"]
    # all non-reverse 4; reverse item 2 raw 1 -> reversed 6
    answers = {i["id"]: (1 if i.get("reverse") else 4) for i in scale["items"]}
    scores = score_assessment(scale, answers)
    # self has 8 non-reverse items at 4 and 7 reverse items at 6
    self_sum = scores["factors"]["self"]["sum"]
    assert self_sum == 8 * 4 + 7 * 6


def test_teacher_ref_total_bands():
    scale = load_scale("teacher_ref.json")
    # non-reverse max 6, reverse raw 1 -> reversed 6
    answers = {i["id"]: (1 if i.get("reverse") else 6) for i in scale["items"]}
    scores = score_assessment(scale, answers)
    assert scores["total_mean"] == 6.0
    assert scores["total_level"] == "good"

    # fair band boundary
    answers = {i["id"]: (3 if i.get("reverse") else 4) for i in scale["items"]}
    scores = score_assessment(scale, answers)
    assert scores["total_level"] == "fair"

    # low band
    answers = {i["id"]: (6 if i.get("reverse") else 1) for i in scale["items"]}
    scores = score_assessment(scale, answers)
    assert scores["total_level"] == "low"
