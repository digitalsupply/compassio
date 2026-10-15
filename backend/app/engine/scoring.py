from typing import Any


def _round(value: float) -> float:
    return round(value, 2)


def score_mht(scale: dict, answers: dict[int, int]) -> dict[str, Any]:
    items = {i["id"]: i for i in scale["items"]}
    validity_ids = set(scale["validity_scale"]["item_ids"])
    subscales = scale["subscales"]

    subscale_scores = {}
    subscale_concerns = {}
    for sub in subscales:
        total = sum(answers.get(iid, 0) for iid in sub["item_ids"])
        subscale_scores[sub["key"]] = {
            "name": sub["name"],
            "score": total,
            "item_count": len(sub["item_ids"]),
            "high_cutoff": sub.get("high_cutoff"),
        }
        if sub.get("high_cutoff") is not None and total >= sub["high_cutoff"]:
            subscale_concerns[sub["key"]] = {
                "name": sub["name"],
                "score": total,
                "cutoff": sub["high_cutoff"],
            }

    validity_score = sum(answers.get(iid, 0) for iid in validity_ids)
    is_valid = validity_score < scale["validity_scale"]["invalid_cutoff"]

    non_validity_items = [iid for iid in items if iid not in validity_ids]
    total_score = sum(answers.get(iid, 0) for iid in non_validity_items)

    total_level = "high"
    total_label = "心理状况较差，焦虑程度较高，需重点关注与特别指导"
    bands = scale["total_score"]["bands"]
    if total_score <= bands[0]["max"]:
        total_level = "normal"
        total_label = bands[0]["label"]
    elif total_score <= bands[1]["max"]:
        total_level = "subthreshold"
        total_label = bands[1]["label"]

    return {
        "scale_id": scale["id"],
        "validity_score": validity_score,
        "is_valid": is_valid,
        "invalid_cutoff": scale["validity_scale"]["invalid_cutoff"],
        "total_score": total_score,
        "total_level": total_level,
        "total_label": total_label,
        "subscales": subscale_scores,
        "subscale_concerns": subscale_concerns,
    }


def score_mssmhs(scale: dict, answers: dict[int, int]) -> dict[str, Any]:
    subscales = scale["subscales"]
    factor_scores = {}
    factor_bands = {}
    total_sum = 0
    total_count = len(scale["items"])

    bands = scale["scoring"]["bands"]
    for sub in subscales:
        s = sum(answers.get(iid, 0) for iid in sub["item_ids"])
        mean = _round(s / len(sub["item_ids"]))
        total_sum += s
        factor_scores[sub["key"]] = {
            "name": sub["name"],
            "sum": s,
            "mean": mean,
            "item_count": len(sub["item_ids"]),
        }
        if mean < bands[0]["max"]:
            level = "normal"
            label = bands[0]["label"]
        elif mean < bands[1]["max"]:
            level = "mild"
            label = bands[1]["label"]
        else:
            level = "moderate_plus"
            label = bands[2]["label"]
        factor_bands[sub["key"]] = {"level": level, "label": label}

    total_mean = _round(total_sum / total_count)
    overall_level = "normal" if total_mean < 2 else "overall_issue"

    return {
        "scale_id": scale["id"],
        "total_sum": total_sum,
        "total_mean": total_mean,
        "overall_level": overall_level,
        "factors": factor_scores,
        "factor_bands": factor_bands,
    }


def score_teacher_ref(scale: dict, answers: dict[int, int]) -> dict[str, Any]:
    items = {i["id"]: i for i in scale["items"]}
    subscales = scale["subscales"]
    scoring = scale["scoring"]

    def raw_value(iid: int) -> int:
        raw = answers.get(iid, 1)
        if items[iid].get("reverse"):
            return 7 - raw
        return raw

    factor_scores = {}
    factor_bands = {}
    total_sum = 0
    for sub in subscales:
        vals = [raw_value(iid) for iid in sub["item_ids"]]
        s = sum(vals)
        mean = _round(s / len(sub["item_ids"]))
        total_sum += s
        factor_scores[sub["key"]] = {
            "name": sub["name"],
            "sum": s,
            "mean": mean,
            "item_count": len(sub["item_ids"]),
        }
        band = scoring["bands"][-1]
        for b in scoring["bands"]:
            if b.get("min") is not None and mean >= b["min"]:
                band = b
                break
        factor_bands[sub["key"]] = {"level": band["level"], "label": band["label"]}

    total_mean = _round(total_sum / len(scale["items"]))
    total_band = scoring["total_bands"][-1]
    for b in scoring["total_bands"]:
        if b.get("min") is not None and total_mean >= b["min"]:
            total_band = b
            break

    return {
        "scale_id": scale["id"],
        "direction": scoring.get("direction", "score_high_is_healthy"),
        "total_sum": total_sum,
        "total_mean": total_mean,
        "total_level": total_band["level"],
        "total_label": total_band["label"],
        "factors": factor_scores,
        "factor_bands": factor_bands,
    }


def score_assessment(scale: dict, answers: dict[int, int]) -> dict[str, Any]:
    scale_id = scale["id"]
    if scale_id == "mht":
        return score_mht(scale, answers)
    if scale_id == "mssmhs":
        return score_mssmhs(scale, answers)
    if scale_id == "teacher_ref":
        return score_teacher_ref(scale, answers)
    raise ValueError(f"Unsupported scale: {scale_id}")
