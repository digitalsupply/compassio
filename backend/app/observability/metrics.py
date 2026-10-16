"""Prometheus metrics for Compassio.

Uses the official ``prometheus-client`` (no fastapi-instrumentator).  All
metric objects are created once at import time against the default registry
and are safe to update from any thread/async task.

Label values are low-cardinality by construction: HTTP routes use the route
*template* (e.g. ``/api/assess/{id}/next``), never the concrete path.
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# Latency buckets (seconds) suggested by the task book.
DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


# ---- HTTP ---------------------------------------------------------------
http_request_duration_seconds = Histogram(
    "compassio_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "route", "status"],
    buckets=DURATION_BUCKETS,
)

http_requests_total = Counter(
    "compassio_http_requests_total",
    "Total HTTP requests handled.",
    ["method", "route", "status"],
)


# ---- LLM ----------------------------------------------------------------
llm_request_duration_seconds = Histogram(
    "compassio_llm_request_duration_seconds",
    "LLM call duration in seconds.",
    ["stage", "model", "outcome"],
    buckets=DURATION_BUCKETS,
)

llm_fallback_total = Counter(
    "compassio_llm_fallback_total",
    "LLM calls that fell back to deterministic rules.",
    ["stage"],
)

llm_requests_total = Counter(
    "compassio_llm_requests_total",
    "LLM requests issued, by selection stage and strategy mode.",
    ["stage", "mode"],  # stage=pick_next_checkpoint|conclusion|ping; mode=fusion|adaptive
)

llm_reachability_total = Counter(
    "compassio_llm_reachability_total",
    "Token-free LLM credential/reachability probes, by outcome.",
    ["outcome"],  # outcome=ok|auth_error|unreachable|config_error
)

# ---- adaptive selection (fusion strategy) --------------------------------
adaptive_llm_consulted_total = Counter(
    "compassio_adaptive_llm_consulted_total",
    "Checkpoints where the LLM was actually consulted.",
)

adaptive_llm_skipped_total = Counter(
    "compassio_adaptive_llm_skipped_total",
    "Item selections where deterministic rules replaced the LLM.",
)


# ---- next-item cache / prefetch ----------------------------------------
next_cache_total = Counter(
    "compassio_next_cache_total",
    "Next-item cache events.",
    # result: hit | miss | prefetch_written | prefetch_error
    # reason (only meaningful for result="miss"): no_prefetch (规则兜底，正常)
    #        | llm_blocked (因等待 LLM 而未命中)
    ["result", "reason"],
)

# 仅当 ``GET /next`` 因需要 LLM 选题而真的同步等待时才观测（规则路径不观测，
# 预取后台任务也不观测）。用于把「命中率高不高」纠偏成「学生是否真的在等 LLM」。
next_llm_wait_seconds = Histogram(
    "compassio_next_llm_wait_seconds",
    "Time a student actually waited for the LLM while fetching the next item.",
    buckets=DURATION_BUCKETS,
)


# ---- business -----------------------------------------------------------
assessments_started_total = Counter(
    "compassio_assessments_started_total",
    "Assessments started.",
    ["scale"],
)

assessments_completed_total = Counter(
    "compassio_assessments_completed_total",
    "Assessments finished.",
    ["scale"],
)

items_answered_total = Counter(
    "compassio_items_answered_total",
    "Items answered.",
    ["scale"],
)

risk_flags_total = Counter(
    "compassio_risk_flags_total",
    "Risk flags raised.",
    ["scale", "severity"],
)

import_created_total = Counter(
    "compassio_import_created_total",
    "Accounts created via import.",
    ["kind"],
)

users_total = Gauge(
    "compassio_users_total",
    "Users by role (refreshed by the health/background collector).",
    ["role"],
)


# ---- dependency health --------------------------------------------------
dependency_up = Gauge(
    "compassio_dependency_up",
    "Dependency reachability (1=up, 0=down).",
    ["dependency"],  # db | redis | llm
)


def set_dependency_up(dependency: str, up: bool) -> None:
    try:
        dependency_up.labels(dependency).set(1 if up else 0)
    except Exception:  # pragma: no cover - metrics must never break requests
        pass


def observe_llm(stage: str, model: str, outcome: str, duration_s: float) -> None:
    try:
        llm_request_duration_seconds.labels(stage, model or "unknown", outcome).observe(
            max(0.0, duration_s)
        )
    except Exception:  # pragma: no cover
        pass


def inc_fallback(stage: str) -> None:
    try:
        llm_fallback_total.labels(stage).inc()
    except Exception:  # pragma: no cover
        pass


def inc_llm_request(stage: str, mode: str) -> None:
    try:
        llm_requests_total.labels(stage, mode or "unknown").inc()
    except Exception:  # pragma: no cover
        pass


def inc_llm_reachability(outcome: str) -> None:
    try:
        llm_reachability_total.labels(outcome or "unknown").inc()
    except Exception:  # pragma: no cover
        pass


def inc_llm_consulted() -> None:
    try:
        adaptive_llm_consulted_total.inc()
    except Exception:  # pragma: no cover
        pass


def inc_llm_skipped() -> None:
    try:
        adaptive_llm_skipped_total.inc()
    except Exception:  # pragma: no cover
        pass


def inc_next_cache(result: str, reason: str = "") -> None:
    try:
        next_cache_total.labels(result, reason or "").inc()
    except Exception:  # pragma: no cover
        pass


def observe_next_llm_wait(duration_s: float) -> None:
    """Record a genuine synchronous LLM wait during ``GET /next`` only."""
    try:
        next_llm_wait_seconds.observe(max(0.0, duration_s))
    except Exception:  # pragma: no cover
        pass


def metrics_payload() -> bytes:
    """Return the current registry scrape in Prometheus text format."""
    return generate_latest()


__all__ = [
    "CONTENT_TYPE_LATEST",
    "DURATION_BUCKETS",
    "http_request_duration_seconds",
    "http_requests_total",
    "llm_request_duration_seconds",
    "llm_fallback_total",
    "llm_requests_total",
    "adaptive_llm_consulted_total",
    "adaptive_llm_skipped_total",
    "next_cache_total",
    "next_llm_wait_seconds",
    "assessments_started_total",
    "assessments_completed_total",
    "items_answered_total",
    "risk_flags_total",
    "import_created_total",
    "users_total",
    "dependency_up",
    "set_dependency_up",
    "observe_llm",
    "inc_fallback",
    "inc_llm_request",
    "inc_llm_consulted",
    "inc_llm_skipped",
    "inc_next_cache",
    "observe_next_llm_wait",
    "metrics_payload",
]
