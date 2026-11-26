# Compassio LLM 成本控制策略详解（结合代码）

> 本文结合 `backend/app/` 下的实际源码，逐层拆解 Compassio 如何把 LLM 调用成本压到最低，同时保证测评不被模型层阻塞。所有结论均标注对应源文件与关键代码片段。

## 一、总览：成本控制的核心思想

Compassio 里真正会烧钱的 LLM 调用只有两类：**选题时的检查点重排**（`engine/adaptive.py`）和**结束时的结论生成**（`engine/conclusion.py`），外加依赖探针的误用。项目没有采用"每题都问模型"的朴素方案，而是围绕四个原则构建成本体系：

1. **能不用就不用**：确定性规则优先，LLM 只在规则无法胜任的稀疏检查点介入。
2. **要用就少用**：候选集裁剪、低温度、JSON 模式、限制 max_tokens，压低单次 token 消耗。
3. **用不了就降级**：超时、异常、无效输出一律回退规则/模板，绝不因模型层阻塞测评。
4. **成本要可见**：每个调用、回退、探针都埋点，让"钱花在哪"可度量、可纠偏。

下面按代码逐项展开。

---

## 二、策略一：fusion 自适应选题（核心成本控制）

### 2.1 三种策略开关

`config.py:76` 定义了 `ADAPTIVE_STRATEGY`，默认 `fusion`：

```python
adaptive_strategy: str = Field(default="fusion", alias="ADAPTIVE_STRATEGY")
```

`adaptive.py:220-231` 给出三种模式的语义：

```
fusion     - rules pick every item; LLM only at sparse checkpoints   # 默认
adaptive   - LLM on every weighted-phase item (legacy, ~84 calls/100)
rules_only - never call the LLM
```

- `fusion`：规则选**每一题**，LLM 仅在稀疏检查点被咨询一次重排。
- `adaptive`：加权阶段每题都问，100 题的 MHT 约 84 次调用（遗留模式，成本高）。
- `rules_only`：完全不调用 LLM。

### 2.2 检查点稀疏化：把 84 次压成约 6 次

`checkpoint.py` 的模块文档（`checkpoint.py:1-6`）直接给出了成本账：

> That turns ~1 call/item (≈84 calls for a 100-item MHT) into ~6 checks.

实现方式是每份测评维护一个整数状态——"下一次检查点到期时的已答题数"，存放于 Redis `compassio:llm_sched:{id}`，TTL 2h（`checkpoint.py:31-32`）：

```python
KEY_PREFIX = "compassio:llm_sched:"
TTL_SECONDS = 2 * 60 * 60  # 2h
```

间隔在 `[ADAPTIVE_LLM_INTERVAL_MIN, ADAPTIVE_LLM_INTERVAL_MAX]` 间随机化（默认 12-20，`config.py:79-80`），且用 `random.Random(f"{assessment_id}:{answered_count}")` 做种子，保证同一测评可确定性回放、不污染全局 RNG（`checkpoint.py:47-56`）：

```python
def _interval(assessment_id: int, answered_count: int) -> int:
    settings = get_settings()
    lo = int(settings.adaptive_llm_interval_min)
    hi = int(settings.adaptive_llm_interval_max)
    ...
    rng = random.Random(f"{assessment_id}:{answered_count}")
    return rng.randint(lo, hi)
```

`should_consult_llm()`（`checkpoint.py:116-132`）推进调度器：状态缺失时初始化为一个随机间隔；到达检查点时推进并返回 `True`。关键幂等保证——**同一 `answered_count` 重复调用不会重复消耗检查点**，因此重发的 `/next` 或后台预取不会"白烧"一次 LLM：

```python
if answered_count >= state:
    await _save(assessment_id, state + _interval(assessment_id, answered_count))
    return True
```

Redis 不可用时透明退化为进程内 `OrderedDict`（容量 500），与 `next_cache.py` 同构（`checkpoint.py:36, 59-75`）。

### 2.3 fusion 模式下的调用决策

`adaptive.py:253-265`：fusion 模式下只有到了检查点才真正调用 LLM，其余时刻直接走规则并计入 `skipped` 指标：

```python
if strategy == "fusion":
    if assessment_id is None:
        consult = True  # 无调度上下文（单测）：保守咨询一次
    else:
        consult = await should_consult_llm(assessment_id, len(answered))
else:
    consult = True

if not consult:
    inc_llm_skipped()
    return ordered[0], None, False, "rule_weighted"
```

`inc_llm_skipped()` 对应指标 `compassio_adaptive_llm_skipped_total`，让"因稀疏化而省下的调用"可观测。

---

## 三、策略二：覆盖阶段免 LLM

选题分两个阶段。覆盖阶段（每个维度先抽 2 题）完全是确定性规则、瞬时返回，**不调用 LLM**。

`adaptive.py:21-22`：

```python
COVERAGE_PER_SUBSCALE = 2
```

`adaptive.py:75-90` 判断是否处于覆盖阶段，`adaptive.py:241-243` 命中即直接返回规则首题，`source="rule_coverage"`：

```python
if is_coverage_phase(scale, answered):
    return ordered[0], None, False, "rule_coverage"
```

这意味着测评开头最密集的那几轮选题零 LLM 成本，把预算留给加权阶段真正需要模型判断的时刻。

---

## 四、策略三：候选集裁剪与低 token 调用

真正调用 LLM 时，从三方面压低单次成本：

### 4.1 只发候选 id，不发题目全文

`adaptive.py:245-246` 限制候选数量（默认 20，`config.py:82`），且只传 `item_id` 和所属维度，**不传题目文本**，大幅压缩输入 token：

```python
top_n = max(1, int(settings.llm_pick_top_n))
candidates = ordered[:top_n]
...
candidate_payload = [
    {"item_id": iid, "subscale": sub_of.get(iid, "")} for iid in candidates
]
```

### 4.2 低温度 + JSON 模式 + 限制 max_tokens

`adaptive.py:296-308` 的调用参数：

```python
result = await asyncio.wait_for(
    provider.chat(
        messages=[...],
        temperature=0.1,        # 低温度，保证重排稳定
        max_tokens=400,         # 推理模型留足思考 token
        response_format={"type": "json_object"},  # 强制 JSON，省格式开销
    ),
    timeout=CHECKPOINT_TIMEOUT_S,
)
```

结论生成同理，`conclusion.py:72-74`：`temperature=0.6`、`max_tokens=1200`，并要求模型"只用中文输出一段结论，不输出 JSON 或 Markdown"（`conclusion.py:69`），避免结构化输出带来的额外 token。

### 4.3 输出严格校验，越界即丢弃

`_extract_llm_order()`（`adaptive.py:177-200`）只接受候选集内的 id，重复项去重，空结果视为无效：

```python
allowed = set(candidates)
llm_order: list[int] = []
ordered_ids = parsed.get("ordered_ids")
if isinstance(ordered_ids, list):
    for raw in ordered_ids:
        if (isinstance(raw, int) and not isinstance(raw, bool)
            and raw in allowed and raw not in llm_order):
            llm_order.append(raw)
```

无效输出不会重试，直接 `fallback_used=True` 走规则，避免为坏结果反复烧钱。

---

## 五、策略四：超时回退与降级优先

### 5.1 8 秒硬超时

`adaptive.py:25` 与 `SPEC §6.2` 第 4 条一致：

```python
CHECKPOINT_TIMEOUT_S = 8.0
```

`adaptive.py:296-297` 用 `asyncio.wait_for` 包裹调用，超时直接回退：

```python
result = await asyncio.wait_for(provider.chat(...), timeout=CHECKPOINT_TIMEOUT_S)
```

`adaptive.py:324-328` 捕获超时和一切异常，`fallback_used=True`，绝不向上抛错：

```python
except asyncio.TimeoutError:
    fallback_used = True
    outcome = "timeout"
except Exception:
    fallback_used = True
```

### 5.2 provider 不可用即全链路降级

`provider.py` 没有 provider 时，`adaptive.py:249-251` 选题走规则，`conclusion.py:21-23` 结论走模板：

```python
# adaptive.py
if provider is None or strategy == "rules_only":
    inc_llm_skipped()
    return ordered[0], None, False, "rule_weighted"

# conclusion.py
if provider is None:
    inc_fallback("conclusion")
    return (_template_conclusion(scale_id, scores, risk_flags), True)
```

`openwiki/llm/provider-and-configuration.md` 总结为一句话原则：**No assessment can be blocked by the model layer.**（没有任何测评会被模型层阻塞。）

### 5.3 网关 400 立即失败，不重试

`provider.py:79-82`：网关返回 400 时直接抛 `LLMError`，不做无意义的重试（配置错误重试只会重复烧钱）；其他传输错误重试一次后以 502 风格错误抛出：

```python
if resp.status_code == 400:
    raise LLMError(f"LLM gateway returned 400: {resp.text}", status_code=400)
...
except Exception as exc:
    last_error = exc
    if attempt == 0:
        continue
raise LLMError(f"LLM request failed: {last_error}", status_code=502)
```

---

## 六、策略五：预取缓存隐藏延迟成本

这是最容易被忽略、但效果最显著的一招。`next_cache.py` 在每次答完题后**异步预取**下一题并缓存，使下一次 `GET /next` 命中缓存直接返回（<20ms），**不产生任何 LLM 调用**。

### 6.1 触发时机

`assess.py:317`（答完题后）和 `assess.py:162,173`（开始/断点续答时）都触发：

```python
schedule_prefetch(id)   # answer 后
schedule_prefetch(existing.id)  # start 复用进行中测评时
```

`schedule_prefetch()`（`next_cache.py:174-192`）是 fire-and-forget，不阻塞当前请求：

```python
task = loop.create_task(prefetch_next(assessment_id))
_background_tasks.add(task)
task.add_done_callback(_background_tasks.discard)
```

### 6.2 缓存与消费

主存是 Redis（key `compassio:next:{assessment_id}`，TTL 300s），Redis 不可用退化为进程内 `OrderedDict`（容量 500，TTL 300s）（`next_cache.py:35-37`）：

```python
KEY_PREFIX = "compassio:next:"
TTL_SECONDS = 300
LOCAL_MAX_ITEMS = 500
```

`read_next()` 是**一次性消费**（读到即删，`next_cache.py:90-101`），避免过期题号被复用：

```python
raw = await client.get(key)
if raw:
    await client.delete(key)   # 一次性消费
    inc_next_cache("hit")
    return json.loads(raw)
```

`assess.py:216-224` 命中缓存就直接用，`used_cache=True`，完全跳过 `pick_next_item`：

```python
cached = await read_next(id)
if cached is not None:
    cached_item = cached.get("item_id")
    if cached_item is None or cached_item not in answered:
        chosen = cached_item
        ...
        used_cache = True
```

### 6.3 缓存失败永不影响调用方

`prefetch_next()`（`next_cache.py:155-171`）吞掉所有异常（`CancelledError` 除外），失败仅记指标 `prefetch_error`，调用方无感知。缓存层的任何故障都不会演变成一次同步 LLM 调用。

### 6.4 缓存命中率归因纠偏

`assess.py:236-243` 把缓存未命中细分，避免把"规则兜底"误记为"等 LLM 烧钱"：

```python
if source in ("llm_fusion", "llm", "rule_fallback"):
    inc_next_cache("miss", reason="llm_blocked")   # 真等 LLM
else:
    inc_next_cache("miss", reason="no_prefetch")   # 规则兜底，正常
```

---

## 七、策略六：双层健康探针（免额度 + 付费节流）

依赖探针是隐形的烧钱大户。`test_llm_probe.py:1-6` 记录了历史教训：

> 之前 30s 巡检每次都调用真实推理接口（stage=ping），24 小时不间断，单日约 1.6 万次请求，纯属额度浪费。

项目用**两层探针**彻底解决了这个问题。

### 7.1 `reachable()`：免额度探活（主力）

`provider.py:150-185` 只发 `{"model": ...}`，**故意不带 `messages`**，网关在推理前就以 400 拒绝，凭据有效即判 ok，**0 token 消耗**：

```python
resp = await client.post(
    url, headers=headers, json={"model": self.config.model}
)
```

状态分类（`provider.py:178-184`）：

| 响应 | 判定 | 含义 |
| --- | --- | --- |
| 2xx/400/422/429 | `ok` | 凭据已接受，4xx 是请求体校验失败，未进入推理 |
| 401/403 | `auth_error` | key 被拒，重试无意义 |
| 404/405 | `unreachable` | 路径/端点错误 |
| 5xx/网络错误 | `unreachable` | 上游故障，值得重试 |
| 缺 session 头 | `config_error` | 不发 HTTP 请求 |

30s 依赖巡检循环（`main.py:332-341`）用的就是这层，节流间隔 `LLM_REACHABILITY_INTERVAL_SECONDS`（默认 900s，`config.py:65-67`）。

### 7.2 `ping()`：付费探活（深度验证）

`provider.py:117-148` 发一次真实 `max_tokens: 5` 的 chat，仅在需要深度验证时、按 `LLM_PING_INTERVAL_SECONDS`（默认 1800s，`config.py:68-70`）节流调用。

**关键成本细节**：`ping()` 刻意**不复用** `chat()`。因为推理模型会把 5 token 的预算全耗在思考上、返回空内容，`chat()` 会把它当成截断并重试（放大到约 1200 token），导致一次 ping 变成两次上游推理（`provider.py:117-124`，注释原文）：

> Deliberately does not reuse chat: a reasoning model spends the tiny max_tokens budget on thinking, so chat would read the empty content as a truncation and retry with ~1200 tokens (线上实测一次 ping 产生两次上游推理调用）。

`test_llm_probe.py:357-373` 专门锁定这个行为：一次 ping 必须只产生一次上游请求。

### 7.3 跨 worker 共享 + 名额串行化

`main.py:200-205` 注释说明：uvicorn 以 `--workers 2` 运行，进程内缓存会让两个 worker 各说各话。因此探活结果和"本轮谁去探活"都放 Redis，全集群共享：

```python
LLM_HEALTH_KEY = "compassio:deps:llm"
LLM_PROBE_LOCK_KEY = "compassio:deps:llm:probe"
LLM_PING_LOCK_KEY = "compassio:deps:llm:ping"
```

`_maybe_llm_check()`（`main.py:249-279`）的逻辑链：

1. Redis 有新鲜健康记录 → 直接复用，**不访问网关**（所有 worker 拿到同一答案）。
2. 免额度探活名额（`SET NX EX`，TTL 30s）未抢到 → 本轮跳过。
3. 到间隔 → 先跑 `reachable()`；**只有探活通过**且付费 ping 名额也到点，才跑 `ping()`。
4. 成功按完整间隔（900s）记 TTL；**失败只记 60s**（`LLM_FAILURE_RETRY_SECONDS`，`main.py:196`），便于快速恢复，避免一次网络抖动让依赖状态挂满整个间隔。

`test_llm_probe.py:155-190` 验证：2 pod × 2 worker 每个间隔只探活一次，付费 ping 未到期时只补免额度探活。

### 7.4 网络抖动重试，但凭据失败不重试

`_probe_llm_reachable()`（`main.py:145-181`）对 `unreachable` 重试 3 次（`LLM_PROBE_ATTEMPTS=3`，间隔 1s），但 `auth_error` 是确定性结论，**不重试**（`test_llm_probe.py:306-312`），避免为坏 key 反复烧钱。

---

## 八、策略七：推理模型截断重试的成本边界

`provider.py:72-103` 处理推理模型（deepseek 等）的隐藏思考：若 `content` 为空且 `finish_reason=length`，说明预算被思考耗光，自动把 `max_tokens` 放大到 `min(max(4×, 1200), 4000)` 重试一次：

```python
if (parsed is None or (isinstance(parsed, str) and not parsed.strip()))
    and finish_reason == "length"
    and truncated_retry_left > 0
):
    truncated_retry_left -= 1
    payload["max_tokens"] = min(max(max_tokens * 4, 1200), 4000)
    continue
```

这个重试只针对**真正有内容价值**的调用（选题、结论），且仅重试一次、有上限封顶。如前所述，`ping()` 明确排除此逻辑，把成本边界控制在"业务调用可重试一次、探针绝不重试"。

---

## 九、策略八：可观测性让成本透明

`metrics.py` 为每一次 LLM 相关行为埋点，让成本可度量、可纠偏：

| 指标 | 含义 | 对应代码 |
| --- | --- | --- |
| `compassio_llm_requests_total` | LLM 请求计数（按 stage/mode） | `inc_llm_request()` `metrics.py:166` |
| `compassio_adaptive_llm_consulted_total` | 实际咨询 LLM 的检查点数 | `inc_llm_consulted()` `metrics.py:180` |
| `compassio_adaptive_llm_skipped_total` | 规则替代 LLM 的次数 | `inc_llm_skipped()` `metrics.py:187` |
| `compassio_llm_fallback_total` | 回退到规则/模板的次数 | `inc_fallback()` `metrics.py:159` |
| `compassio_llm_reachability_total` | 免额度探活结果 | `inc_llm_reachability()` `metrics.py:173` |
| `compassio_next_cache_total` | 缓存命中/未命中（区分 llm_blocked） | `inc_next_cache()` `metrics.py:194` |
| `compassio_next_llm_wait_seconds` | 学生真实等待 LLM 的时长 | `observe_next_llm_wait()` `metrics.py:201` |
| `compassio_llm_request_duration_seconds` | LLM 调用耗时直方图 | `observe_llm()` `metrics.py:150` |

**等待时长只在前台 `/next` 统计**（`adaptive.py:344-347`，`observe_llm_wait=True`），后台预取不算学生等待，避免把后台算力消耗误记为用户体验成本：

```python
if observe_llm_wait:
    # 只有前台 /next 才把真实等待计入；后台预取不算学生等待
    observe_next_llm_wait(duration)
```

---

## 十、成本控制参数汇总

| 参数 | 默认值 | 位置 | 作用 |
| --- | --- | --- | --- |
| `ADAPTIVE_STRATEGY` | `fusion` | `config.py:76` | 选题策略，fusion 稀疏化调用 |
| `ADAPTIVE_LLM_INTERVAL_MIN/MAX` | `12/20` | `config.py:79-80` | 检查点间隔，控制稀疏度 |
| `LLM_PICK_TOP_N` | `20` | `config.py:82` | 候选集上限，压输入 token |
| `LLM_ENABLED` | `true` | `config.py:59` | 总开关，关闭即零 LLM |
| `LLM_TIMEOUT_S` | `30` | `config.py:58` | 单次调用超时 |
| `LLM_REACHABILITY_INTERVAL_SECONDS` | `900` | `config.py:65-67` | 免额度探活间隔 |
| `LLM_PING_INTERVAL_SECONDS` | `1800` | `config.py:68-70` | 付费探活间隔（0=关闭） |
| `CHECKPOINT_TIMEOUT_S` | `8.0` | `adaptive.py:25` | 检查点调用硬超时，超时回退 |
| `PREFETCH_ENABLED` | `true` | `config.py:29` | 预取缓存开关 |
| `LLM_FAILURE_RETRY_SECONDS` | `60` | `main.py:196` | 探活失败后快速重试的短 TTL |
| `LLM_PROBE_ATTEMPTS` | `3` | `main.py:193` | 探活网络抖动重试次数 |

---

## 十一、实测效果

把各层策略叠加后的账：

- **选题**：100 题 MHT，`fusion` 模式下规则选 94 题、LLM 仅在约 6 个检查点重排（`checkpoint.py` 模块注释），相比 `adaptive` 的 ~84 次，**调用量下降约 93%**。
- **覆盖阶段**：开头每维度 2 题的密集期零 LLM（`adaptive.py:241-243`）。
- **单次调用**：候选只传 id、低温度、JSON 模式、max_tokens 400/1200，单次 token 远低于全量上下文方案。
- **探针**：30s 巡检用免额度 `reachable()`，付费 `ping()` 每 30 分钟最多一次且跨 worker 共享，彻底消除历史"单日 1.6 万次请求"的浪费（`test_llm_probe.py:1-6`）。
- **预取缓存**：答完题即异步预取，`/next` 命中缓存零 LLM，把同步等待也藏到后台。
- **兜底**：超时、异常、无效输出、provider 不可用均回退规则/模板，成本再低也不牺牲可用性。

## 十二、相关源码索引

| 文件 | 职责 |
| --- | --- |
| `backend/app/llm/provider.py` | 统一 provider、chat/ping/reachable、截断重试 |
| `backend/app/llm/service.py` | `resolve_provider` 配置解析（DB 优先于环境） |
| `backend/app/llm/presets.py` | 9 个 provider 预设 |
| `backend/app/engine/adaptive.py` | 选题主逻辑、覆盖阶段免 LLM、检查点调用 |
| `backend/app/engine/checkpoint.py` | fusion 检查点调度器（稀疏化核心） |
| `backend/app/engine/conclusion.py` | 结论生成与模板回退 |
| `backend/app/next_cache.py` | 预取缓存（隐藏延迟成本） |
| `backend/app/routers/assess.py` | `/next` 缓存消费、`/answer` 预取触发 |
| `backend/app/routers/llm.py` | LLM 配置管理 API（单默认、密钥掩码） |
| `backend/app/main.py` | 双层探针调度、跨 worker 共享 |
| `backend/app/config.py` | 所有成本相关配置项 |
| `backend/app/observability/metrics.py` | 成本可观测指标 |
| `backend/tests/test_llm_probe.py` | 探针节流/免额度/单次 ping 行为 |
| `backend/tests/test_next_cache.py` | 预取缓存行为 |
