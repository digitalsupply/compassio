# LLM 选下一题：越界防护与信度保障

> 结合 Compassio 自适应评估流程（`app/engine/adaptive.py` + `app/engine/scoring.py`），详解 LLM 在"每隔几道题介入选下一题"时，如何保证所选题目**必在权威题库内**，以及 LLM 是否**破坏量表信度**。

## 一、核心结论

- **不越界**：三重机制保证 LLM 选的题必在题库内，不能造题、不能越界；
- **不破坏信度**：LLM 只改"出题顺序"，不改"题目、题量、计分"，而信度依赖后三者。

## 二、如何保证 LLM 生成的下一题"正好在题库内"

LLM **不是自由生成题号**，而是**从规则选出的候选集中"重排序"**。三重机制兜底，全在 `app/engine/adaptive.py`。

### 2.1 机制一：候选集约束（LLM 只能重排，不能自由生成）

```python
# adaptive.py:239-246
ordered = select_candidate_order(scale, answered_ids)   # 从题库剩余题中规则排序
top_n = max(1, int(settings.llm_pick_top_n))
candidates = ordered[:top_n]                            # 取前 top_n 个作为候选集
```

- `ordered` 来自 `scale["items"]`（权威题库）的**剩余题**；
- prompt 明确把候选集喂给 LLM，要求返回这些候选的 `ordered_ids`：

```python
# adaptive.py:277-285
prompt = (
    "...Re-order the candidate items... "
    f"candidates: {candidate_payload}\n"   # 候选集是题库内的，LLM 只能从中选
)
```

**LLM 的角色是"给候选集排个序"，不是"从题库外造题"。**

### 2.2 机制二：白名单校验（候选集外的题号一律丢弃）

即使 LLM 不听话返回了题库外的题号，也会被过滤：

```python
# adaptive.py:177-200 _extract_llm_order
allowed = set(candidates)                # 白名单 = 候选集
for raw in ordered_ids:
    if (isinstance(raw, int)
        and raw in allowed               # ← 候选集外的直接丢
        and raw not in llm_order):
        llm_order.append(raw)
return llm_order                         # 只返回候选集内的
```

**LLM 返回的题号必须 `in allowed`，否则丢弃。** 题库外的题根本进不来。

### 2.3 机制三：回退机制（LLM 异常时用规则结果）

LLM 超时、报错、返回无效时，回退到规则选的题：

```python
# adaptive.py:315-328
if llm_order:
    rest = [iid for iid in candidates if iid not in llm_order]
    chosen = (llm_order + rest)[0]       # 选中的仍是候选集内的
else:
    fallback_used = True                 # LLM 返回无效 → 回退
except asyncio.TimeoutError:
    fallback_used = True                 # 超时 → 回退
except Exception:
    fallback_used = True                 # 异常 → 回退
# 最终 fallback 时 source=rule_fallback，用 candidates[0]（规则选的，必在题库内）
```

**三重保证**：候选集约束 → 白名单校验 → 异常回退。LLM 选的题**必然在题库内**，不能越界、不能造题。

## 三、LLM 是否破坏题库信度？——不破坏

**信度（reliability）依赖的是：题目标准化、计分规则固定、题量固定。** LLM 只改了"出题顺序"，这三项一个没动。

### 3.1 计分与出题顺序完全解耦

```python
# scoring.py:25-34  score_mht
def score_mht(scale, answers: dict[int, int]):
    for sub in subscales:
        total = sum(answers.get(iid, 0) for iid in sub["item_ids"])
        ...
# assess.py:309  评估完成时统一计分
scores = score_assessment(payload, answered)
```

- 计分函数只接收 `answers: dict[int, int]`（**题号 → 分值**）；
- 按题号取分值求和，**与这些题按什么顺序作答完全无关**；
- 1+2=3，2+1=3——顺序不改变总分、不改变各维度分。

**LLM 改顺序，计分结果不变。** 这是不破坏信度的根本。

### 3.2 题量固定，答完才结束

```python
# adaptive.py:233-237
remaining_ids = all_ids - answered_ids
if not remaining_ids:
    return None, None, False, "finished"   # 必须答完量表所有题
```

LLM **只决定顺序，不决定题量**。必须答完 `scale["items"]` 的全部题才结束，LLM 不能少选、不能多选。信度依赖的"题量固定"得以保证。

### 3.3 题目内容不变

LLM 只读 `scale["items"]`，**不修改题目文本、选项、计分规则**。权威量表的内容原封不动。

### 3.4 覆盖阶段纯规则，保证维度覆盖

```python
# adaptive.py:242-243
if is_coverage_phase(scale, answered):
    return ordered[0], None, False, "rule_coverage"   # 前几题纯规则，LLM 不介入
```

覆盖阶段（每个子量表先抽 2 题）是**确定性规则**，LLM 不介入。这保证每个维度都被测到，**避免 LLM 凭偏好跳过某些维度**，保护量表的覆盖性。

### 3.5 LLM 的"推理分析"不参与计分

LLM 的介入分两种，都不碰计分：

```python
# assess.py:309, 406
scores = score_assessment(payload, answered)              # 计分：纯规则，基于 answers
summary, fallback_used = await generate_conclusion(...)   # LLM 只生成结论文字
```

- **选下一题**（checkpoint）：只重排候选，不改计分；
- **生成结论**（`generate_conclusion`）：只产出 `llm_summary` 文字描述，**不参与计分**。分数是纯规则算的。

## 四、LLM 到底改了什么？——只改顺序

| 维度 | 是否被 LLM 改变 | 代码依据 |
| --- | --- | --- |
| 题目内容 | ❌ 不变 | 只读 `scale["items"]` |
| 题目数量 | ❌ 不变 | 答完所有题才 `finished` |
| 计分规则 | ❌ 不变 | `score_assessment` 纯规则，与顺序无关 |
| **出题顺序** | ✅ **只改这个** | LLM 重排候选集 |

**信度依赖的是前三项，与顺序无关。** 所以 LLM 不破坏信度。

## 五、测量学上的注意点

虽然不破坏信度，但有两点要说清楚，避免误解：

1. **顺序效应是自适应测验固有的，非 LLM 引入**：LLM 改变题目顺序，可能带来锚定效应、疲劳效应。但这是**任何变序施测都有的**，固定顺序量表同样存在。LLM 只是让顺序更智能，没有引入新的测量偏差。

2. **检查点时机是确定性的，可复现**：`checkpoint.py` 用 `random.Random(f"{assessment_id}:{answered_count}")` 生成间隔，状态存 Redis，**同一评估重放结果一致**，"每隔几道题介入"的时机是确定的、可审计的，不是随机乱调。

## 六、总结

| 问题 | 答案 |
| --- | --- |
| 如何保证 LLM 选的题在题库内？ | 三重机制：候选集约束（LLM 只重排候选，不自由生成）+ 白名单校验（候选外丢弃）+ 回退机制（异常用规则结果） |
| LLM 是否破坏信度？ | **不破坏**。计分与顺序完全解耦（按题号求和），题量固定（答完才结束），题目不变，LLM 结论不参与计分，覆盖阶段纯规则保证维度覆盖 |
| LLM 到底改了什么？ | **只改出题顺序**，不改题目、题量、计分。信度依赖后三者，与顺序无关 |

> 一句话：LLM 在权威量表的框架内，智能决定"接下来出哪道题"的顺序，让作答路径更贴合学生当前状态；题目、题量、计分全由固定规则掌控，LLM 越不了界、也动不了信度。
