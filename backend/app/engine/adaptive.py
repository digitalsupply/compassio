from typing import Any, Awaitable, Callable

from app.llm.provider import LLMProvider


CoverageFilter = Callable[[dict], Awaitable[tuple[int | None, str | None, bool]]]


def _subscale_threshold(scale: dict, sub_key: str) -> float:
    scale_id = scale["id"]
    if scale_id == "mht":
        for sub in scale.get("subscales", []):
            if sub["key"] == sub_key:
                return float(sub.get("high_cutoff", 8))
        return 8.0
    if scale_id == "mssmhs":
        return 3.0
    if scale_id == "teacher_ref":
        return 3.5
    return 3.0


def _risk_weight(scale: dict, sub: dict, answered: dict[int, int]) -> float:
    answered_items = [iid for iid in sub["item_ids"] if iid in answered]
    if not answered_items:
        return 0.0
    vals = [answered[iid] for iid in answered_items]
    total = sum(vals)
    threshold = _subscale_threshold(scale, sub["key"])
    scale_id = scale["id"]

    if scale_id == "mht":
        # raw score approaching 8
        return min(total / threshold, 2.0)
    if scale_id == "teacher_ref":
        # higher is healthier; risk when mean is low
        mean = total / len(answered_items)
        gap = max(0.0, threshold - mean)
        return min(gap / threshold, 2.0)
    # mssmhs
    mean = total / len(answered_items)
    return min(mean / threshold, 2.0)


def _validity_ids(scale: dict) -> list[int]:
    return scale.get("validity_scale", {}).get("item_ids", [])


def select_candidate_order(
    scale: dict, answered_ids: set[int]
) -> list[int]:
    """Deterministic ordering of remaining item ids."""
    all_items = {i["id"]: i for i in scale["items"]}
    remaining = [iid for iid in all_items if iid not in answered_ids]

    validity = _validity_ids(scale)
    validity_remaining = [iid for iid in validity if iid in remaining]

    subscales = scale.get("subscales", [])
    answered = {iid: 0 for iid in answered_ids}  # values not needed for ordering after validity

    # Group remaining by subscale (an item belongs to exactly one subscale here)
    sub_remaining: dict[str, list[int]] = {sub["key"]: [] for sub in subscales}
    for iid in remaining:
        if iid in validity_remaining:
            continue
        sub = all_items[iid].get("subscale")
        if sub and sub in sub_remaining:
            sub_remaining[sub].append(iid)

    # Coverage: subscales with fewer than 2 answered items come first
    answered_by_sub = {
        sub["key"]: sum(1 for iid in sub["item_ids"] if iid in answered_ids)
        for sub in subscales
    }

    coverage_items = []
    weighted_items = []
    for sub in subscales:
        key = sub["key"]
        items = sorted(sub_remaining[key])
        if answered_by_sub[key] < 2:
            coverage_items.extend(items)
        else:
            weight = _risk_weight(scale, sub, answered)
            weighted_items.append((weight, key, items))

    # Sort weighted stage: higher risk first, then by original subscale order
    weighted_items.sort(key=lambda x: (-x[0], [s["key"] for s in subscales].index(x[1])))
    weighted_flat = []
    for _, _, items in weighted_items:
        weighted_flat.extend(items)

    return validity_remaining + coverage_items + weighted_flat


def _build_subscale_profile(scale: dict, answered: dict[int, int]) -> list[dict]:
    profile = []
    for sub in scale.get("subscales", []):
        ids = [iid for iid in sub["item_ids"] if iid in answered]
        if not ids:
            continue
        vals = [answered[iid] for iid in ids]
        profile.append(
            {
                "key": sub["key"],
                "name": sub["name"],
                "answered": len(ids),
                "total": sum(vals),
                "mean": round(sum(vals) / len(ids), 2),
            }
        )
    return profile


async def pick_next_item(
    scale: dict,
    answered: dict[int, int],
    provider: LLMProvider | None,
    transition_only: bool = False,
) -> tuple[int | None, str | None, bool]:
    """Returns (item_id, transition, fallback_used). item_id None => finished."""
    all_ids = {i["id"] for i in scale["items"]}
    answered_ids = set(answered.keys())
    remaining_ids = all_ids - answered_ids
    if not remaining_ids:
        return None, None, False

    ordered = select_candidate_order(scale, answered_ids)
    candidates = ordered[:3]

    fallback_used = False
    chosen = candidates[0]
    transition = None

    if provider is not None:
        profile = _build_subscale_profile(scale, answered)
        prompt = (
            "You are an adaptive test assistant. ONLY choose the next item_id from the "
            "candidate list and optionally provide a short (<20 chars) caring transition sentence. "
            "Do not skip required items. Do not modify questions. "
            "Return strictly JSON: {\"item_id\": int, \"transition\": \"...\"}.\n\n"
            f"scale: {scale['id']}\n"
            f"subscale_profile: {profile}\n"
            f"candidates: {candidates}\n"
        )
        try:
            result = await provider.chat(
                messages=[
                    {"role": "system", "content": "You only output JSON with keys item_id and transition."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=80,
                response_format={"type": "json_object"},
            )
            parsed = result.get("content")
            if isinstance(parsed, dict):
                llm_item = parsed.get("item_id")
                transition = parsed.get("transition")
                if isinstance(llm_item, int) and llm_item in candidates:
                    chosen = llm_item
                else:
                    fallback_used = True
            else:
                fallback_used = True
        except Exception:
            fallback_used = True

    return chosen, transition, fallback_used
