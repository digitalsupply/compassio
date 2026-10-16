import asyncio
from time import perf_counter
from typing import Any

from app.config import get_settings
from app.llm.provider import LLMProvider
from app.observability.metrics import inc_fallback, inc_llm_request, observe_llm
from app.observability.tracing import set_span_attributes, start_span


async def generate_conclusion(
    scale: dict,
    scores: dict[str, Any],
    risk_flags: list[dict],
    provider: LLMProvider | None,
) -> tuple[str, bool]:
    """Returns (summary, fallback_used)."""
    scale_id = scale["id"]
    is_teacher = scale_id == "teacher_ref"

    if provider is None:
        inc_fallback("conclusion")
        return (_template_conclusion(scale_id, scores, risk_flags), True)

    if is_teacher:
        prompt = (
            "你是一位心理支持助手。请根据以下教师自评结果，写一段120-200字的自我关怀提示。\n"
            "要求：不使用\"问题/障碍/诊断\"等字眼；强调自我关怀、可行建议、求助渠道；\n"
            "结尾用一句温暖的话提醒\"这不是评价，只是关照自己的机会\"。\n\n"
            f"结果：{scores}\n"
            f"提示标记：{risk_flags}\n"
        )
    else:
        severities = {f.get("severity") for f in (risk_flags or [])}
        has_critical = "critical" in severities
        has_high = "high" in severities
        priority_rule = ""
        if has_critical:
            priority_rule = (
                "【最高优先级】预警含 critical：第一句必须直接提示存在需要立即关注的风险信号，"
                "请学生尽快告诉信任的老师/家长或学校心理老师，并给出陪伴式安抚；"
                "严禁先说\"整体平稳/状态良好\"，也不得淡化风险；之后再用温和语气补充得分概况与建议。\n"
            )
        elif has_high:
            priority_rule = (
                "【优先级】预警含 high：先用一句温和但清楚的提醒点出需要重点关注的方面，再补充得分概况与建议。\n"
            )
        prompt = (
            "你是一位学校心理健康筛查助手。请根据以下量表得分与预警标记，写一段120-200字的结论。\n"
            "要求：非诊断语言（\"筛查结果提示…建议…\"）；正向框架；1-2条可执行建议；\n"
            "出现较高风险时建议联系心理老师；结尾一句关怀语\"这不是标签，只是一次看见自己的机会\"。\n"
            "分量表与总分的等级（subscales 中的 level/level_label，high=明显倾向、mild=一定困扰、normal=无明显倾向）"
            "已由系统确定性判定，请严格与其保持一致，不得改判或自行调整严重程度。\n"
            + priority_rule +
            f"结果：{scores}\n"
            f"预警：{risk_flags}\n"
        )

    stage = "conclusion"
    model = getattr(getattr(provider, "config", None), "model", "unknown")
    started = perf_counter()
    outcome = "ok"
    span = start_span("llm.conclusion", {"scale": scale_id, "stage": stage})
    with span as active:
        try:
            inc_llm_request(stage, get_settings().adaptive_strategy)
            result = await provider.chat(
                messages=[
                    {"role": "system", "content": "你只用中文输出一段结论，不输出JSON或Markdown。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.6,
                max_tokens=1200,  # 推理模型需预留思考 token，否则正文可能为空
            )
            content = result.get("content")
            if isinstance(content, dict):
                content = content.get("summary") or content.get("conclusion") or str(content)
            if isinstance(content, str) and len(content.strip()) >= 20:
                duration = perf_counter() - started
                set_span_attributes(
                    active,
                    {
                        "scale": scale_id,
                        "stage": stage,
                        "outcome": "ok",
                        "fallback": False,
                        "duration_ms": round(duration * 1000, 3),
                    },
                )
                observe_llm(stage, model, "ok", duration)
                return content.strip(), False
        except asyncio.TimeoutError:
            outcome = "timeout"
        except Exception:
            outcome = "error"
        duration = perf_counter() - started
        if outcome == "ok":
            outcome = "error"
        set_span_attributes(
            active,
            {
                "scale": scale_id,
                "stage": stage,
                "outcome": outcome,
                "fallback": True,
                "duration_ms": round(duration * 1000, 3),
            },
        )

    observe_llm(stage, model, outcome, duration)
    inc_fallback(stage)
    return (_template_conclusion(scale_id, scores, risk_flags), True)


def _template_conclusion(scale_id: str, scores: dict[str, Any], risk_flags: list[dict]) -> str:
    if scale_id == "teacher_ref":
        level = scores.get("total_level", "fair")
        if level == "good":
            base = "你目前整体状态良好，继续保持对自己的觉察与关怀。"
        elif level == "fair":
            base = "你某些维度的资源值得关注，不妨给自己安排一段休息与放松的时间。"
        else:
            base = "你近期的压力可能较大，请优先照顾睡眠与休息，必要时向信任的人或专业支持求助。"
        if risk_flags:
            base += "记住：求助是专业者的习惯，不是软弱。"
        base += "这不是评价，只是一次关照自己的机会。"
        return base

    level = scores.get("total_level") or scores.get("overall_level") or "normal"
    if level in ("high", "moderate_plus"):
        base = "筛查结果提示你目前部分维度压力较高，建议尽快联系学校心理老师或专业支持。"
    elif level in ("subthreshold", "mild"):
        base = "筛查结果提示你有一些值得关注的情绪信号，可以尝试规律作息、适度运动和与信任的人交流。"
    else:
        base = "筛查结果显示你目前心理状态整体平稳，继续保持健康的生活方式。"

    high_names = [
        info.get("name")
        for info in (scores.get("subscales") or {}).values()
        if isinstance(info, dict) and info.get("level") == "high" and info.get("name")
    ]
    if high_names:
        base += f"其中「{'、'.join(high_names)}」维度提示需重点关注。"

    if risk_flags:
        severities = {f["severity"] for f in risk_flags}
        if "critical" in severities:
            base += "系统检测到高风险信号，请务必重视并寻求帮助。"
    base += "这不是标签，只是一次看见自己的机会。"
    return base
