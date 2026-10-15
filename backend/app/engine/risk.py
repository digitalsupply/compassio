from typing import Any


def evaluate_condition(
    condition: dict,
    answers: dict[int, int],
    scores: dict[str, Any] | None = None,
) -> bool:
    scores = scores or {}

    if "any_items_equal" in condition:
        for entry in condition["any_items_equal"]:
            if answers.get(entry["item"]) == entry["value"]:
                return True
        return False

    if "any_items_gte" in condition:
        for entry in condition["any_items_gte"]:
            if answers.get(entry["item"], 0) >= entry["value"]:
                return True
        return False

    if "total_score_gte" in condition:
        return (scores.get("total_score") or 0) >= condition["total_score_gte"]

    if "subscale_mean_gte" in condition:
        for entry in condition["subscale_mean_gte"]:
            key = entry["subscale"]
            mean = 0.0
            if "factors" in scores:
                mean = scores["factors"].get(key, {}).get("mean", 0)
            elif "subscales" in scores:
                # mht subscale scores are raw sums, not means; not used by this rule
                mean = scores["subscales"].get(key, {}).get("score", 0)
            if mean >= entry["value"]:
                return True
        return False

    if "subscales_mean_gte_3_count" in condition:
        count = 0
        for factor in scores.get("factors", {}).values():
            if factor.get("mean", 0) >= 3:
                count += 1
        return count >= condition["subscales_mean_gte_3_count"]

    if "validity_score_gte" in condition:
        return (scores.get("validity_score") or 0) >= condition["validity_score_gte"]

    if "total_mean_lte" in condition:
        return (scores.get("total_mean") or 999) <= condition["total_mean_lte"]

    return False


def evaluate_risks(
    scale: dict,
    answers: dict[int, int],
    scores: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    flags = []
    for rule in scale.get("risk_rules", []):
        if evaluate_condition(rule["condition"], answers, scores):
            flags.append(
                {
                    "rule_id": rule["id"],
                    "severity": rule["severity"],
                    "message": rule["message"],
                }
            )
    return flags


def should_notify_admin(flag: dict, scale_id: str) -> bool:
    """Teacher reference results never generate admin notifications."""
    if scale_id == "teacher_ref":
        return False
    severity = flag.get("severity")
    return severity in ("high", "critical")
