import asyncio
from time import perf_counter
from typing import Any, Awaitable, Callable

from app.config import get_settings
from app.engine.checkpoint import should_consult_llm
from app.llm.provider import LLMProvider
from app.observability.metrics import (
    inc_fallback,
    inc_llm_consulted,
    inc_llm_request,
    inc_llm_skipped,
    observe_llm,
    observe_next_llm_wait,
)
from app.observability.tracing import set_span_attributes, start_span


CoverageFilter = Callable[[dict], Awaitable[tuple[int | None, str | None, bool]]]

# 覆盖阶段：每个维度先抽 2 题。该阶段选题纯规则、瞬时，无需 LLM。
COVERAGE_PER_SUBSCALE = 2

# 检查点 LLM 调用的硬超时（SPEC §6.2 第 4 条：>8s 回退规则）。
CHECKPOINT_TIMEOUT_S = 8.0

# LLM 调用指标使用的 stage 名。
CHECKPOINT_STAGE = "pick_next_checkpoint"


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


def is_coverage_phase(scale: dict, answered: dict[int, int]) -> bool:
    """True while any subscale still has fewer than ``COVERAGE_PER_SUBSCALE``
    answered items.

    Uses the same notion of coverage as :func:`select_candidate_order`, so the
    fast path and the candidate ordering agree on when coverage ends.
    """
    subscales = scale.get("subscales", [])
    if not subscales:
        return False
    answered_ids = set(answered.keys())
    for sub in subscales:
        count = sum(1 for iid in sub["item_ids"] if iid in answered_ids)
        if count < COVERAGE_PER_SUBSCALE:
            return True
    return False


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


def _subscale_lookup(scale: dict) -> dict[int, str]:
    lookup: dict[int, str] = {}
    for sub in scale.get("subscales", []):
        for iid in sub["item_ids"]:
            lookup[iid] = sub["key"]
    return lookup


def _clean_transition(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return value[:20]


def _extract_llm_order(parsed: dict, candidates: list[int]) -> list[int]:
    """Validate the LLM ordering; IDs outside the candidate set are dropped.

    Accepts the new ``ordered_ids`` shape and the legacy single ``item_id``
    shape.  Duplicates collapse.  An empty result means "invalid" and the
    caller falls back to the deterministic rule order.
    """
    allowed = set(candidates)
    llm_order: list[int] = []
    ordered_ids = parsed.get("ordered_ids")
    if isinstance(ordered_ids, list):
        for raw in ordered_ids:
            if (
                isinstance(raw, int)
                and not isinstance(raw, bool)
                and raw in allowed
                and raw not in llm_order
            ):
                llm_order.append(raw)
    else:  # legacy shape: {"item_id": int, ...}
        legacy = parsed.get("item_id")
        if isinstance(legacy, int) and not isinstance(legacy, bool) and legacy in allowed:
            llm_order.append(legacy)
    return llm_order


async def pick_next_item(
    scale: dict,
    answered: dict[int, int],
    provider: LLMProvider | None,
    transition_only: bool = False,
    assessment_id: int | None = None,
    observe_llm_wait: bool = False,
) -> tuple[int | None, str | None, bool, str]:
    """Returns ``(item_id, transition, fallback_used, source)``.

    ``source`` is one of ``finished``, ``rule_coverage`` (deterministic
    coverage phase, LLM deliberately skipped), ``rule_weighted`` (rules picked,
    no LLM at this step), ``llm_fusion`` (LLM re-ranked the candidates at a
    checkpoint), ``llm`` (legacy ``adaptive`` strategy) or ``rule_fallback``
    (LLM errored / returned an invalid ordering).  ``item_id`` is ``None`` when
    the assessment is complete.

    Strategy (``ADAPTIVE_STRATEGY``):
      * ``fusion`` (default) — rules pick every item; the LLM is consulted only
        at sparse checkpoints spaced ``[ADAPTIVE_LLM_INTERVAL_MIN,
        ADAPTIVE_LLM_INTERVAL_MAX]`` items apart (see ``engine.checkpoint``).
      * ``adaptive`` — the LLM is consulted on every weighted-phase item.
      * ``rules_only`` — the LLM is never consulted.
    """
    settings = get_settings()
    strategy = (settings.adaptive_strategy or "fusion").strip().lower()
    if strategy not in ("fusion", "adaptive", "rules_only"):
        strategy = "fusion"  # 防御式：未知值按默认 fusion 处理
    mode = "adaptive" if strategy == "adaptive" else "fusion"

    all_ids = {i["id"] for i in scale["items"]}
    answered_ids = set(answered.keys())
    remaining_ids = all_ids - answered_ids
    if not remaining_ids:
        return None, None, False, "finished"

    ordered = select_candidate_order(scale, answered_ids)

    # ---- 覆盖阶段免 LLM：确定性规则，瞬时返回 ----
    if is_coverage_phase(scale, answered):
        return ordered[0], None, False, "rule_coverage"

    top_n = max(1, int(settings.llm_pick_top_n))
    candidates = ordered[:top_n]

    # ---- rules_only / 未配置 provider：零 LLM ----
    if provider is None or strategy == "rules_only":
        inc_llm_skipped()
        return ordered[0], None, False, "rule_weighted"

    # ---- 加权阶段：fusion 只在检查点调用；adaptive 每题调用 ----
    if strategy == "fusion":
        if assessment_id is None:
            # 无调度上下文（如直接单测调用）：按“到点”处理，保守地咨询一次。
            consult = True
        else:
            consult = await should_consult_llm(assessment_id, len(answered))
    else:
        consult = True

    if not consult:
        inc_llm_skipped()
        return ordered[0], None, False, "rule_weighted"

    # 真正调用 LLM 的检查点。
    inc_llm_consulted()
    inc_llm_request(CHECKPOINT_STAGE, mode)

    scale_id = scale["id"]
    profile = _build_subscale_profile(scale, answered)
    sub_of = _subscale_lookup(scale)
    candidate_payload = [
        {"item_id": iid, "subscale": sub_of.get(iid, "")} for iid in candidates
    ]
    prompt = (
        "You are an adaptive test assistant. Re-order the candidate items and "
        "optionally provide a short (<20 chars) caring transition sentence. "
        "Do not skip required items. Do not modify questions. "
        "Return strictly JSON: {\"ordered_ids\": [int, ...], \"transition\": \"...\"}.\n\n"
        f"scale: {scale_id}\n"
        f"subscale_profile: {profile}\n"
        f"candidates: {candidate_payload}\n"
    )

    fallback_used = False
    chosen = candidates[0]
    transition = None
    model = getattr(getattr(provider, "config", None), "model", "unknown")
    started = perf_counter()
    outcome = "ok"
    span = start_span("llm.pick_next_checkpoint", {"scale": scale_id, "stage": CHECKPOINT_STAGE})
    with span as active:
        try:
            result = await asyncio.wait_for(
                provider.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": "You only output JSON with keys ordered_ids and transition.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=400,  # 推理模型留足思考 token
                    response_format={"type": "json_object"},
                ),
                timeout=CHECKPOINT_TIMEOUT_S,
            )
            parsed = result.get("content")
            if isinstance(parsed, dict):
                llm_order = _extract_llm_order(parsed, candidates)
                transition = _clean_transition(parsed.get("transition"))
                if llm_order:
                    # 按 LLM 顺序重排候选（仅顺序，不影响题量/计分）。
                    rest = [iid for iid in candidates if iid not in llm_order]
                    chosen = (llm_order + rest)[0]
                else:
                    fallback_used = True
                    transition = None
            else:
                fallback_used = True
        except asyncio.TimeoutError:
            fallback_used = True
            outcome = "timeout"
        except Exception:
            fallback_used = True
        duration = perf_counter() - started
        if fallback_used and outcome == "ok":
            outcome = "error"
        set_span_attributes(
            active,
            {
                "scale": scale_id,
                "stage": CHECKPOINT_STAGE,
                "outcome": outcome,
                "fallback": fallback_used,
                "duration_ms": round(duration * 1000, 3),
            },
        )

    observe_llm(CHECKPOINT_STAGE, model, outcome, duration)
    if observe_llm_wait:
        # 只有前台 ``/next``（observe_llm_wait=True）才把这段真实等待计入
        # compassio_next_llm_wait_seconds；后台预取不算学生等待。
        observe_next_llm_wait(duration)
    if fallback_used:
        inc_fallback(CHECKPOINT_STAGE)

    if fallback_used:
        source = "rule_fallback"
    elif strategy == "adaptive":
        source = "llm"
    else:
        source = "llm_fusion"
    return chosen, transition, fallback_used, source
