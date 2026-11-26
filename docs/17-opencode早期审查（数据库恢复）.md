# Compassio 代码架构分析（opencode 早期审查 · 从损坏数据库恢复）

> **来源**：opencode 会话 `ses_eb6d782eaffe0wmDCyknqRhQj8`「代码架构分析、质量评价与优缺点总结」
> **模型**：opencode / deepseek-v4.1-flash-free
> **恢复方式**：opencode 数据库损坏后，用 Python sqlite3 从 `session_message` 表导出（见 `docs/04-opencode数据库损坏与修复实录.md`）
> **原始提问**：「分析代码架构 评价质量 总结优缺点」
> **说明**：本报告为 opencode 独立产出，未做任何人工修改；Hermes 的复核见文末附注。

---

我已经通读了整个仓库（后端 ~7.9k 行 Python、前端 ~4.9k 行 Vue/TS、CI/CD 与部署清单），并实际运行了测试。下面是架构分析、质量评价与优缺点总结。

---

## 一、项目概览

**Compassio** 是一个「大模型驱动的校级心理健康测评系统」，monorepo 三部分：

| 层 | 技术栈 | 规模 |
|---|---|---|
| 后端 | Python 3.11 / FastAPI(async) / SQLAlchemy 2.0 async + asyncpg / Pydantic v2 / JWT | ~7.9k 行 |
| 前端 | Vue 3 + Vite + TS + Element Plus + Pinia + ECharts | ~4.9k 行 |
| 交付 | docker-compose + K8s kustomize + Tekton/Harbor/ArgoCD GitOps | 12 个清单文件 |

核心业务：三套量表（MHT / MSSMHS / teacher_ref）的**确定性计分** + **LLM 自适应出题**（融合策略）+ 风险预警 + 班级结果分发/导出。

---

## 二、架构分层评价

### 后端分层清晰（这是最大亮点）

```
routers/          接口层（FastAPI + RBAC 依赖注入）
  └── engine/     领域引擎（纯确定性，禁止 LLM 参与计分）
        ├── scoring.py    计分
        ├── risk.py       风险规则
        ├── adaptive.py   自适应选题
        └── checkpoint.py LLM 检查点调度
  └── llm/        LLM 抽象（provider/service/presets）
  └── observability/  指标 / 追踪 / 日志
```

- **确定性引擎与大模型严格解耦**：`scoring.py` 完全读 JSON 规则、无副作用；LLM 只影响「下一题的顺序」和「结论文案」，绝不参与计分。这是心理健康场景的关键安全边界，落地得很干净。
- **LLM 抽象合理**：`provider.py` 是 OpenAI 兼容的薄封装，`service.py` 决定「DB 配置优先，env 兜底」，`presets.py` 预置 8 家。统一 `chat()` + 两个探针（`ping()` 付费、`reachable()` 免额度），职责分明。

### 「优雅降级」贯穿全局

这是该项目工程成熟度最突出的地方，每一处外部依赖都有回退：

| 依赖 | 失败时 | 位置 |
|---|---|---|
| LLM 选题 | 回退规则顺序 `rule_fallback` | `adaptive.py:320` |
| LLM 结论 | 回退模板结论 | `conclusion.py:112` |
| Redis | 回退进程内 LRU（TTL 500 条） | `next_cache.py` / `checkpoint.py` |
| 预取 | `/next` 同步重算 | `assess.py:221` |
| 可观测 | 所有埋点 `except` 吞掉，绝不阻断请求 | `metrics.py` |

### 成本工程：融合策略（值得单独点出）

`checkpoint.py` + `adaptive.py` 把「每题调 LLM」（100 题→~84 次）压缩到「每 12~20 题一个检查点」（~5~8 次），且：
- 检查点用 `random.Random(f"{assessment_id}:{answered_count}")`——**确定性可重放，不污染全局 RNG**；
- 状态存 Redis + 进程内兜底，跨 2 worker 一致；
- `should_consult_llm` 对相同 `answered_count` 幂等，避免 `/next` 重发或预取重复消费检查点。

### 可观测性（生产级）

`observability/metrics.py` 用官方 `prometheus-client`，**路由用模板而非具体路径**（`_route_template` 用正则替换 `{id}`）杜绝标签基数爆炸——这是很专业的细节。加上 OTLP 追踪、依赖健康 Gauge（db/redis/llm）、多 worker 共享健康值走 Redis。

---

## 三、质量评价（含实证）

我运行了后端测试：

```
1 failed, 96 passed in 71.74s
```

**失败的是一个随机性 flaky 测试**，暴露了真实问题：

`tests/test_print_roster.py:79` 断言 `temp in roster.text`。生成的初始密码来自 `_charset = "...!@#$%&*"`（含 `&`），而 `print-roster` 对密码做了 `html.escape`（`users.py:181`）。本次跑到 `qQx&aAdg`，HTML 里成了 `qQx&amp;aAdg`，断言失败。**约 10% 概率随机红灯**——CI 不可信。这是测试与实现耦合缺陷，不是产品功能 bug（浏览器渲染后密码正确）。

### 其他具体质量问题

1. **死代码 / 重复查询**：`assess.py:325-339` 有两条**完全相同**的 `select(Notification)...`，第一条结果被丢弃。
2. **迁移体系缺失**：`requirements.txt` 声明了 `alembic>=1.13`，`SPEC.md` 也列了 `backend/alembic/`，但仓库**根本没有 alembic 目录**。实际靠 `Base.metadata.create_all` + 硬编码的 `_apply_light_migrations`（`main.py:86`，两条 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`）。表结构演进会越来越脆。
3. **README 与实现不符**：README 写「Redis（会话/限流）」，但全局搜索 `rate|limit|throttle|lockout` **没有任何登录限流/防爆破**。Redis 实际只用于缓存、健康状态、检查点调度。
4. **敏感信息处理**：`LLMConfigOut` 直接回传明文 `api_key`（`schemas.py:186`）；`api_key` 明文入库；`SECRET_KEY` 默认 `change-me-in-production`；JWT 存 localStorage（XSS 可窃取）、24h 过期、无刷新/吊销机制。
5. **N+1 查询**：`import_.py:_unique_username` 每行一次查询（887 行→887 次）；`report.py:47` 每个班级 2 次查询；`users.py` 账号列表**无分页**（SPEC 明写「分页」），3000 账号全量返回。
6. **权限过宽**：`_load_assessment`（`assess.py:185`）允许管理员访问任意测评，因此 `next`/`answer`/`finish` 三个写接口管理员都能替学生操作；只有 `report` 端点做了收窄。
7. **全局可变模块状态**：`db.engine`、`AsyncSessionLocal`、`next_cache._local_cache`、`checkpoint._local_state`、`main._LAST_LLM_CHECK` 都是模块级全局，测试隔离与多进程正确性依赖外部（Redis）兜底。
8. **代码重复**：`_gen_password` 和 `_charset` 在 `import_.py` 与 `users.py` 各写一份；`must_change_password`（恒 false）与 `distributed_to_teacher_id/at`（已废弃）等历史包袱保留在模型中。
9. **导入健壮性**：`_read_file` 直接 `load_workbook(上传文件)`，只按扩展名校验，无大小限制——超大 xlsx 可能造成资源耗尽。
10. **文档漂移**：SPEC 列出的 `POST /reports/dispatch`、分页等已移除/未实现（代码有 NOTE 说明，但 SPEC 未同步）。
11. **前端无任何测试、无 ESLint/Prettier 配置**；`HomeView.vue`(518) / `AdminAccounts.vue`(425) 偏大的单文件组件，业务/样式/请求混在一起，缺少 composables 抽象；错误处理 `ElMessage.error(e.response?.data?.detail || ...)` 到处重复。

### 测试覆盖

好的部分：97 个用例覆盖计分、风险、权限隔离、导出、自适应、LLM 探针、可观测性——**核心高风险逻辑都有测试**，尤其权限隔离（`test_permissions.py`）。

不足：**测试全跑 SQLite in-memory**，而生产是 PostgreSQL。JSONB、`ILIKE`、`ALTER TABLE` 迁移路径在生产才生效，测试覆盖不到——这是「测试绿但线上可能翻车」的典型缝隙。

---

## 四、总结

### 优点 👍

- **领域分层优秀**：确定性引擎 / LLM / 可观测 / 接口四层解耦，心理健康场景的「LLM 不参与计分」安全边界落地扎实。
- **降级思维成熟**：LLM、Redis、预取、埋点处处有回退，可用性优先。
- **成本工程有想法**：融合策略把 LLM 调用量降一个数量级，且可重放、幂等。
- **可观测性专业**：Prometheus 标签基数受控、OTLP 追踪、依赖 Gauge、多 worker 共享状态。
- **隐私硬约束清晰**：教师结果对管理员永不可见，用 `user_id` 过滤 + 角色白名单 + 量表白名单三重保证；教师预警不入通知表。
- **文档文化好**：SPEC + 15 篇编号纪要，决策可追溯。
- **交付完整**：compose 与 K8s 双形态 + GitOps 全自动发布。

### 缺点 / 风险 👎

- **测试不可信**：存在 ~10% 概率随机失败的 flaky 用例（HTML 转义 × 随机密码）；且只跑 SQLite，掩盖了 Postgres 差异。
- **无正式迁移**：依赖 `create_all` + 硬编码 ALTER，schema 演进脆弱。
- **安全缺口**：无登录限流、明文 API key 回传/入库、弱默认 SECRET_KEY、JWT 存 localStorage 且无吊销。
- **可扩展性隐患**：N+1 查询、账号列表无分页、导入逐行查库，与「3000 账号/300 并发」目标有差距。
- **工程细节**：死代码、重复代码、过宽的管理员写权限、全局可变状态、前端零测试与大组件。
- **文档漂移**：README/SPEC 描述的能力与实现不一致（限流、分页、分发端点）。

### 建议优先级

| 优先级 | 事项 |
|---|---|
| P0 | 修 flaky 测试（断言前对密码做同样的 `html.escape`，或从 charset 去掉 HTML 特殊字符）；补 Postgres 集成测试 |
| P0 | 登录限流（Redis 已就绪，加 `SET NX EX` 计数即可）；`api_key` 出参掩码；启动强校验 `SECRET_KEY` |
| P1 | 引入 Alembic 替换 `create_all`+硬编码 ALTER；账号列表分页 |
| P1 | 清理死查询/重复代码；收窄管理员写接口权限 |
| P2 | 前端加 Vitest + ESLint，拆分大组件；导入加大小限制；同步 SPEC/README |

**总体结论**：这是一个**业务理解到位、工程成熟度中上**的交付——领域建模、降级策略、成本控制、可观测性明显高于一般课程/外包项目；但**测试可靠性、数据库迁移、安全加固和可扩展性**是明显短板，属于「能跑、能上生产做试点，但离长期可维护的工业级项目还差一档」。

如果需要，我可以直接动手修复 P0 项（flaky 测试 + 登录限流 + api_key 掩码）。

---

## 附：与后续两轮审查的对照（Hermes 注）

本报告是最早的一轮 opencode 审查（数据库损坏前）。其后又跑了 `docs/05`（deepseek-v4.1-flash-free 重跑）与 `docs/16`（glm-5.3-flash-free）。三者交叉对照要点：

| 发现 | 本报告 | docs/05 | docs/16 | Hermes 复核 |
|---|---|---|---|---|
| `test_print_roster` flaky（HTML 转义 × 随机密码） | ✅ 已实测抓到（1 failed） | ✅ 已抓到 | ❌ 漏（单跑撞上好结果） | ✅ 连跑 30 次 = 4 次失败（13.3%） |
| `_maybe_create_notification` 重复查询 | ✅ | ✅ | ✅ | ✅ |
| 无 Alembic 迁移 | ✅ | ✅ | ✅ | ✅ |
| `_gen_password` 用 `random` 而非 `secrets` | ❌ 漏 | ❌ 漏 | ✅ 独有 | ✅ 成立 |
| `item_order` 静默不落库 | ❌ 漏（未读到该细节） | ✅ 独有（已实测复现） | ❌ 漏 | ✅ 成立 |
| 管理员可替学生调用 next/answer/finish | ✅ 独有 | ❌ 漏 | ❌ 漏 | — |
| 测试全跑 SQLite、掩盖 Postgres 差异 | ✅ 独有 | 部分提及 | ❌ 漏 | — |
| 导入无文件大小限制（资源耗尽） | ✅ 独有 | ❌ 漏 | ❌ 漏 | — |
| JWT 无吊销 + localStorage 存 token | ✅ | 部分（未提 localStorage） | ✅ | ✅ 成立 |

**本报告的独有发现**（另两份都漏）：管理员写接口权限过宽（`_load_assessment` 允许 admin 访问任意测评，`next`/`answer`/`finish` 三个写接口未收窄）、测试只用 SQLite 掩盖 Postgres 差异、导入无大小限制。
**结论**：三轮独立审查各有盲区与独有发现，交叉验证的项可信度最高；单一模型的结论不能直接当作完整覆盖。
