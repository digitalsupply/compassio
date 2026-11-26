# Compassio 独立代码审查报告

> 审查方式：静态代码通读 + 实际运行测试（`pytest`）
> 审查对象：`/root/compassio` @ `main`（HEAD `192d3f1`）
> 审查日期：2026-10-17
> 审查范围：`backend/app`（routers / engine / llm / observability）、`frontend/src`、`deploy`、`cicd`、测试与文档
> 说明：本报告为**独立第三方视角**，不复用仓库内既有分析文档的结论；所有结论均标注证据位置，动态结论标注实测命令。

---

## 〇、审查方法与事实基线

| 项 | 值 |
|---|---|
| 后端应用代码 | `backend/app` ≈ **5466** 行 Python |
| 后端测试 | `backend/tests` ≈ **2421** 行，**95** 个 `test_*` 函数（参数化后收集 **97** 个用例） |
| 前端代码 | `frontend/src` ≈ **4831** 行（Vue SFC + TS），**35** 个源文件 |
| 目测量表库 | `mht.json` / `mssmhs.json` / `teacher_ref.json`（禁改文件） |
| 实测测试 | `cd backend && .venv/bin/python -m pytest -q` → **96 passed, 1 failed**（70s） |
| 数据类型 | PostgreSQL 生产 / SQLite 测试（`JSONB with_variant(JSON)` 降级） |

> **本次实测结论先行**：测试并非全绿。唯一失败用例暴露了「随机密码 + HTML 转义」的脆弱断言，详见 §5.3。

---

## 一、项目定位（来自 README.md / SPEC.md）

Compassio（心育罗盘）是一个**大模型驱动的校级心理健康测评系统**，定位「发展性筛查参考，不构成医学诊断」，强调「不贴标签、不制造焦虑」。核心能力：

- **三套量表**：MHT（小学四年级–高中，100 题，含测谎效度量表）、MSSMHS（中学生，60 题×10 因子）、教师参考版（60 题×4 维度，越高越健康，`is_reference: true`）。
- **三种角色**：校级管理员（导入名单/发号/预警/班级报告/LLM 配置/题库替换）、班主任（本班学生结果 + 本人自评）、学生（自适应作答 + 本人报告）。
- **大模型安全边界**（SPEC §6 / README 明确写死）：
  - LLM **只做两件事**——实时调整出题顺序、生成结论文案；
  - **绝不参与计分**（计分为纯确定性引擎）；
  - 失败/超时一律回退到规则/模板，不影响可用性；
  - 教师结果**永不**进管理员通知，任何接口不向 admin 暴露教师个人测评内容。
- **成本策略 `fusion`**：规则负责每一题选题，LLM 每 12–20 题随机触发一个检查点；一份 100 题 MHT 约 5–8 次调用（而非 84 次），可用 `rules_only` 完全关闭。
- **双部署形态**：`deploy/compose`（单机 4 命令）与 `deploy/k8s`（kustomize + ArgoCD GitOps）。

项目工程目标清晰、边界约束写得非常细（尤其隐私与「LLM 不碰计分」两条硬规则），这是后续评价代码质量的重要参照系。

---

## 二、代码结构与模块划分

### 2.1 后端 `backend/app`

| 层 | 文件 | 职责 | 评价 |
|---|---|---|---|
| 入口 | `main.py`(519) | lifespan 建表/轻量迁移/装载题库；依赖探活（db/redis/llm）；30s 后台巡检；可观测性中间件；`/metrics`、`/api/health(/live)` | 职责偏多，但内聚于「应用生命周期 + 依赖健康」 |
| 配置 | `config.py`(82) | Pydantic Settings，env 驱动，`lru_cache` | 简洁规范 |
| 存储 | `db.py`(90) | 懒加载 engine/sessionmaker/redis 单例；`JsonType` 方言变体 | 干净；有进程级全局单例 |
| 模型 | `models.py`(207) | 9 张表 ORM（users/classes/scale_defs/assessments/responses/results/notifications/llm_configs/audit_logs） | 关系完整，含班级↔班主任双向约束 |
| DTO | `schemas.py`(326) | Pydantic v2 入参/出参 | 覆盖完整 |
| 安全 | `security.py`(80) | JWT 签发/校验、bcrypt、`require_role` RBAC 依赖 | 依赖注入方式清晰 |
| 路由 | `routers/`(10 个) | auth / import_ / users / assess / notify / report / teacher / admin / llm / scales | HTTP 层薄，业务下沉到 engine |
| 领域引擎 | `engine/` | `scoring.py`(181) 确定性计分、`adaptive.py`(353) 选题、`risk.py`(78) 风险规则、`checkpoint.py`(142) LLM 检查点调度、`conclusion.py`(150) 结论生成 | **分层最亮眼的一层**：计分/风险为纯函数、可单测 |
| LLM 抽象 | `llm/` | `provider.py`(185) OpenAI 兼容 + `extra_headers` 头注入 + 免额度探活、`presets.py`(51) 9 家预置、`service.py`(46) DB 默认配置优先 | 抽象干净，无重依赖（纯 httpx） |
| 可观测性 | `observability/` | `metrics.py`(242) Prometheus、`tracing.py`(166) OTLP(可禁用)、`logging.py`(87) 结构化 JSON + trace_id | 三件套齐全，且「观测不得成为可用性依赖」 |
| 支撑 | `next_cache.py`(205)、`export_service.py`(241) | 下一题预取缓存（Redis/进程内降级）、xlsx/csv 导出 | 复用良好（admin 与班主任共用导出构建） |

**关键设计亮点**：`engine/scoring.py` 与 `engine/risk.py` 是**无副作用的纯函数**，输入是量表 JSON + 作答字典，输出是分数结构；LLM 交互被隔离在 `llm/` 与 `engine/adaptive.py`/`conclusion.py` 内，并在**所有失败路径**回退到确定性的规则/模板。这是「LLM 不参与计分」这一硬约束能在代码层面成立的根本原因。

### 2.2 前端 `frontend/src`

- **技术栈**：Vue 3 `<script setup>` + TypeScript + Element Plus + Pinia + Vue Router；ECharts 仅用于雷达图。
- **结构**：
  - `api/client.ts`(34)：axios 实例 + 请求拦截注入 `Bearer` + 响应拦截统一处理 401（登录/改密接口的 401 不整页跳转）。
  - `api/services.ts`(181)：按域分组的 **类型化** 接口封装（auth/assess/users/notify/report/teacher/llm/scales/import）。
  - `stores/`：`auth.ts`(63)（token/role + `hasValidSession` 防脏会话死循环）、`notify.ts`(81)（轮询未读）。
  - `router/index.ts`(135)：按 `meta.role` 做**集中式**路由守卫，含「token 与角色不一致就清会话」「未知路径兜底回首页」。
  - `views/` 15 个（学生/教师/管理员三端）+ `components/` 8 个（`AssessRun`、`ReportCard`、`CriticalBanner` 等）。
- **类型**：`types/index.ts`(250) 集中定义，与后端 Pydantic 对齐。

前端整体是**典型的、克制的 SPA 分层**：视图 / API 封装 / 状态 / 路由守卫边界清楚，没有引入多余抽象。

---

## 三、代码质量评价

### 3.1 分层（优）

- 后端符合「routers 只做 HTTP 与鉴权、engine 承载领域逻辑、llm 封装外部依赖、observability 横切」的分层，且依赖方向单一（routers → engine → llm）。
- 纯函数化的计分/风险引擎带来了**可测试性**：`test_scoring.py` / `test_risk.py` 直接喂字典断言，不依赖 DB。
- 导出逻辑抽到 `export_service.py`，被管理员 `/admin/reports/export` 与班主任 `/teacher/class-export` **复用**，避免重复。

### 3.2 类型标注（中上）

- ORM 全面使用 `Mapped[...]` / `mapped_column`；安全、缓存、provider 均带类型标注；Pydantic DTO 完整。
- **扣分项**：
  - 领域结果大量使用 `dict[str, Any]`（`scores`、`risk_flags`），丢失结构约束，靠文档约定（`scoring.py` 返回结构无对应模型）。
  - 前端 `tsconfig.json` 显式 `"strict": false`、`"noUnusedLocals": false`、`"noUnusedParameters": false`，且存在 `role.value = res.data.role as Role`、`(localStorage.getItem(...) as any)` 等 `any` 逃逸——**自建 TS 工程却关掉了严格模式**，类型收益被削弱。

### 3.3 错误处理（优，但有暗礁）

- **正面**：LLM 超时（`CHECKPOINT_TIMEOUT_S=8` / `asyncio.wait_for`）、异常、非法 JSON 一律回退规则；结论生成失败回退模板并记 `fallback_used`；观测组件全部 `try/except` 包裹且「不得阻断请求」；缓存/Redis 不可用降级到进程内。
- **暗礁**：
  - 后端 `main.py` 依赖探活有较多元余的 `except Exception: pass`，问题会被静默吞掉。
  - 前端 **11 处** `catch { /* ignore */ }`（`grep` 实测），如 `StudentAssess.vue:77`、`AdminAccounts.vue` 多处、`stores/notify.ts:54`——静默吞错不利于线上排障。
  - `_maybe_create_notification` 存在**先查一次丢弃、再查一次**的重复查询（`assess.py:325-339`），属明显冗余/疑似未清理的调试残留。

### 3.4 测试覆盖（中上，但本次实测未全绿）

- 覆盖：计分边界（`test_scoring`）、风险规则（`test_risk`）、**权限与隐私硬规则**（`test_permissions`：学生 403、教师互看 403、admin 无教师结果）、自适应与回退（`test_adaptive`）、LLM 探针（`test_llm_probe` 用 `httpx.MockTransport`，覆盖 400/401/404/429/5xx/网络异常）、导入、导出、预取缓存、可观测性。**95 个用例、领域逻辑覆盖扎实**。
- **测试质量优点**：`test_adaptive.py` 用 `RecordingProvider` 脚本化 LLM 行为（valid / invalid_json / timeout / outside_ids），对「候选集约束、过渡语缺失不阻塞」等契约做了真实断言。
- **测试质量短板**：
  - 本次实测 **1 个用例失败**（详见 §5.3），且是**非确定性**的——随机密码字符集含 `&`，被 HTML 转义为 `&amp;`，断言 `temp in roster.text` 概率性失败（约 13%）。
  - 缺并发/多 worker 场景测试（而代码里恰好有大量依赖 Redis 跨进程一致性的逻辑）。
  - 测试依赖真实量表 JSON（`scales/data/*.json`），是集成风格而非隔离单测；`conftest.py` 在 import 前改 `os.environ` 属必要但脆弱的手法。
  - **前端零测试**：无 Vitest/单测，`package.json` 只有 `dev`/`build`/`preview`。

---

## 四、优点清单（明确）

1. **领域逻辑与 LLM 严格解耦**：计分为纯确定性函数，LLM 仅在选题/文案两个出口，且全部失败路径可回退模板。硬约束「LLM 不参与计分」在代码层真实成立。 ✅
2. **隐私硬规则有代码 + 测试双重保障**：`teacher_ref` 不进通知（`risk.should_notify_admin` 直接返回 False）、不进 admin 报表/导出（`_CLASS_REPORT_SCALES`/`EXPORT_SCALES` 白名单）、admin 看教师报告 403（`test_permissions` 断言）。 ✅
3. **成本工程意识强**：`fusion` 融合策略 + `checkpoint.py` 用 `random.Random(f"{id}:{count}")` 做**可复现**的检查点调度，把 100 题 MHT 的 LLM 调用压到 5–8 次，且 `rules_only` 可零成本运行。 ✅
4. **可观测性三件套齐全且自觉**：Prometheus 指标对路由做**模板化**（`_route_template` 避免基数爆炸）、OTLP 可一键禁用、结构化 JSON 日志带 `trace_id` 便于 Loki↔Tempo 跳转；并有 `next_llm_wait_seconds` 等**面向真实体验**的指标（区分「学生是否真的在等 LLM」）。 ✅
5. **LLM 抽象务实**：无 LangChain 等重依赖，纯 httpx；`reachable()` 用「故意缺 `messages` 触发 400（凭据有效）/401（凭据无效），两者都不计费」实现**免额度探活**，是很聪明的工程取舍；对推理模型空 content 有自动放大 `max_tokens` 重试。 ✅
6. **测试对领域契约覆盖好**：计分边界、效度作废、reverse 反转、风险 critical、权限隔离、LLM 回退均有真实断言。 ✅
7. **部署与安全基线有意识**：readiness(`/api/health`) 与 liveness(`/api/health/live`) 分离；Dockerfile 主动升 OS 包与 pip/setuptools/wheel 以清 Trivy 可修项；Secret 走 `secretRef`；`passlib` 与 `bcrypt` 版本 pin 有注释解释。 ✅
8. **注释写「为什么」**：如 `models.py` 说明 async 下 `lazy="selectin"` 的原因、`main.py` 解释探活节流与多 worker 共享的必要性，降低维护成本。 ✅

---

## 五、缺点与风险清单（明确，含严重度）

### 5.1 架构与数据一致性（严重度：中高）

| 项 | 证据 | 说明 |
|---|---|---|
| **无数据库迁移体系** | 仓库无 `backend/alembic/` 目录；`main.py:86 _apply_light_migrations` 用裸 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 手工补 2 列 | requirements 里有 `alembic`、SPEC §2 也画了 `alembic/`，但**实际未落地**。scheme 变更靠 `create_all` + 手写 SQL，无版本审计、无回滚、无法在既有库上可靠演进 |
| **`item_order` 实际未落库（已实测复现）** | `assess.py:240-242` 对 `assessment.item_order`（`models.py:122` 普通 `JSON` 列）**原地 `append` 后 commit** | SQLAlchemy 的 `JSON` 列不做可变对象变更追踪（未用 `MutableList`）。我实测：append+commit 后再查仍是 `[]`。即 SPEC §6.2「item_order 存实际出题顺序，报告可回放」**当前是静默失效的**。当前无代码读取该字段，故暂无功能影响，但属真实缺陷，一旦上游要用就会踩雷 |
| **`_maybe_create_notification` 重复查询** | `assess.py:325-331` 查询结果被丢弃，`333-339` 又查一遍 | 明确冗余，且去重逻辑本身是「SELECT 后判断」，非原子，多 worker 下仍有竞态 |
| **N+1 查询 / 无分页** | `report.py:47-105` 逐班查询学生+测评；`users.py:47 list_accounts` 全量返回；`admin.py:17` 审计日志全量 | 规模（≤3000 账号）下可接受，但 SPEC §5 声称 accounts「分页」，实现未分页，存在口径不一致 |

### 5.2 安全（严重度：中高）

| 项 | 证据 | 说明 |
|---|---|---|
| **JWT 密钥弱默认值** | `config.py:35 secret_key="change-me-in-production"` | 若环境变量未设置，服务会用可预测密钥启动并签发/校验 token。生产必须显式覆盖（compose `.env.example` 有占位，但代码无「启动即拒绝默认值」的护栏） |
| **初始密码明文存库并回传** | `models.py:51 initial_password`，`users.py:101,141,269` 明文写入并在 API 响应/打印名单返回 | 数据库泄露即泄露全部账号初始口令；批量重置让 **900+ 账号共用同一份 bcrypt 哈希与同一口令**（`users.py:138`），一处泄露即全校 |
| **无登录限流/锁定** | `routers/auth.py:17 login` 无 rate-limit、无失败计数 | 可被暴力破解；bcrypt rounds=10 只能放缓 |
| **CORS 未显式配置** | `main.py` 无 `CORSMiddleware` | 当前同源（nginx 反代）可用，但缺少显式白名单与纵深防御 |
| **内部基础设施信息仍入库** | `backend/Dockerfile:1`、`frontend/Dockerfile:5`、`cicd/*.yaml`、`deploy/k8s/*`、`deploy/compose/.env.example` 均含私网 IP/域名（`192.168.67.201/202:8443`、`10.0.0.252`、`compassio.xyz`） | docs/14 纪要称「隐去私有部署信息」，但**只清理了应用代码，部署/CI 清单里的内网地址仍在**（另注：`.env.example` 与 `cicd` 里的 `JWT_SECRET` 是无效变量，`config.py` 只读 `SECRET_KEY`，易误导运维） |
| **LLM API Key 明文库中存取** | `models.py:192 api_key` | 未加密，DB 泄露即泄露上游密钥 |

### 5.3 测试（严重度：中）

- **实测 1 例失败且为非确定性**：`tests/test_print_roster.py::test_print_roster_after_reset_and_self_change`。
  根因：`_gen_password` 字符集含 `&`，`print_roster` 对密码做了 `escape()`（正确行为），而断言用 `assert temp in roster.text` 比较**原始明文**，命中 `&` 时变成 `&amp;` 即失败。
  实测证据：`assert '&*prSQW&' in "...&amp;*prSQW&amp;..."`。这是**测试本身的缺陷**（应比较 `escape(temp)` 或固定随机种子），但它意味着「`pytest` 全绿」的 DoD（SPEC §12.1）在约 13% 的运行里不成立。
- 前后端均无并发测试，而跨 worker 一致性是重灾区（见 5.4）。
- 前端 0 测试。

### 5.4 可维护性与工程一致（严重度：中）

| 项 | 证据 | 说明 |
|---|---|---|
| **大量模块级可变全局状态** | `db.py:26,36,70` `engine/AsyncSessionLocal/_redis_client`；`main.py:195,291,418` `_LAST_LLM_CHECK/_LLM_HEALTH/_route_index_cache`；`next_cache.py:40`、`checkpoint.py:36` 进程内字典 | 2 pod×2 worker 下靠 Redis 对齐，逻辑绕；Redis 抖动时各 worker 结论不一致 |
| **`security.py` 重复 import 与导入期固化** | `security.py:11` 与 `:15` 重复 import；`:17 _settings=_get_settings()` 在 import 时固化 `bcrypt_rounds` | 模块导入即读配置，测试里改 settings 不一定生效；冗余且易误改 |
| **热点函数过长** | `adaptive.pick_next_item`（≈150 行）、`main._maybe_llm_check` 逻辑嵌套深 | 可读性下降，应拆分 |
| **前端错误静默** | 11 处 `catch { /* ignore */ }` | 见 §3.3 |
| **前端关闭严格模式** | `tsconfig.json strict:false` + 多处 `as any` | 见 §3.2 |
| **前端主视图偏大** | `HomeView.vue`(518)、`AdminAccounts.vue`(425) | 单文件承载过多，可拆子组件 |

### 5.5 运维/可观测（严重度：低–中）

- 指标、Dashboard 齐备，但**未见告警规则**（如 LLM 持续不可用、依赖 down、5xx 率）——有信号无通知。
- OTLP 采样策略未配置，开启后为全量 trace，量大时成本/噪声高。
- 无 SQL 慢查询日志开关。

---

## 六、评分（1–10）

| 维度 | 评分 | 一句话依据 |
|---|---|---|
| 架构设计 | **8.0** | 分层清晰、LLM 与计分严格解耦、双部署形态成熟；扣分于无迁移体系与全局状态偏多 |
| 代码质量（可读性/一致性/类型） | **7.0** | 命名与注释优秀、纯函数引擎好；扣分于重复查询、`Any` 泛化、前端 `strict:false` 与静默吞错 |
| 错误处理与韧性 | **8.0** | LLM/缓存/观测全链路降级，回退路径完整；扣分于若干 `except: pass` 过宽 |
| 测试覆盖与可信度 | **6.5** | 领域/权限/回退覆盖扎实且有 Mock 契约测试；但**本次实测 1 例非确定性失败**、缺并发与前端测试 |
| 安全性 | **5.5** | 密钥弱默认、明文初始密码/共享哈希、无登录限流、内部 IP 残留 —— 生产化前必须加固 |
| 可观测性 | **8.0** | 指标/追踪/日志三件套 + 基数控制 + 体验型指标；扣分于无告警规则 |
| 领域/业务严谨性 | **8.5** | 计分确定、效度作废、风险规则数据驱动、教师隐私硬隔离，业务正确性有测试背书 |
| 文档与工程规范 | **8.0** | README/SPEC/运维手册/纪要极详尽；扣分于文档与实现存在小口径偏差（如分页、alembic、私网信息清理不彻底） |
| **综合** | **7.5 / 10** | **架构与业务设计属同类小型系统的上游水准，可观测性与成本工程有亮点；主要拖累项是数据迁移缺失、若干安全默认值、以及一个已实证的 `item_order` 缺陷与脆弱的非确定性测试。** |

> 评分口径：7 分为「结构合理、可维护，但生产化前仍需加固」；本项目多处（解耦、隐私、可观测）明显高于 7 分基线，被安全与数据一致性短板回拉，综合定 **7.5**。

---

## 七、优先改进建议（按 ROI 排序）

1. **[P0｜正确性] 修复 `item_order` 落库**：改用 `MutableList.as_mutable(JsonType)`，或在 append 后显式 `flag_modified(assessment, "item_order")`；并补一条回归测试断言顺序持久化。（已实测复现，见 §5.1）
2. **[P0｜安全] 生产化护栏**：启动时若 `SECRET_KEY` 仍为默认值直接 fail-fast；加登录限流/失败锁定（Redis 计数）；`initial_password` 改为一次性 token 或加密存储，批量重置避免全局共享同一哈希。
3. **[P0｜诚信] 修复脆弱测试**：`test_print_roster` 断言改为 `escape(temp) in roster.text`（或对随机源注入固定种子），恢复「`pytest` 全绿」的 DoD。
4. **[P1｜数据] 引入 Alembic 迁移**：以现有 `create_all` 为基线生成首个 revision，替代 `_apply_light_migrations`，让 schema 变更有审计与回滚。
5. **[P1｜清洁] 清理重复查询与信息残留**：删除 `_maybe_create_notification` 的首次查询；统一从 `deploy/`、`cicd/`、Dockerfile 中抽出私网地址到可注入的 overlay/变量，纠正 `.env.example` 里无效的 `JWT_SECRET`。
6. **[P1｜可维护] 收束全局状态**：把探活/缓存节流状态抽成显式对象并统一以 Redis 为准，减轻多 worker 心智负担；顺带清理 `security.py` 的重复 import 与导入期固化。
7. **[P2｜健壮] 补测试**：并发/多 worker 场景、`print_roster` 转义边界、临界分与效度边界加参数化；前端引入 Vitest 做 API 封装与守卫的最小回归；明确错误处理规范，禁止裸 `catch {}`。
8. **[P2｜前端] 提升类型强度**：`strict: true` + 逐步消除 `as any`；把 `HomeView`/`AdminAccounts` 拆分。
9. **[P3｜运维] 补告警与采样**：为 `compassio_dependency_up`、LLM fallback/超时率、5xx 率配置 Alertmanager 规则；开启 Trace 采样。

---

## 八、结论

Compassio 是一个**定位清晰、边界约束写得很死、并把约束落到代码与测试里的中小型系统**。它最值得肯定的三点是：（1）确定性计分与 LLM 的严格解耦，（2）教师隐私硬规则在查询白名单与测试两处同时兜底，（3）以 `fusion` + `checkpoint` 实现的可复现成本控制与「面向学生真实等待」的可观测性。这些都超出同类小项目的平均水平。

同时，它也存在**必须在上生产前解决**的短板：没有数据库迁移体系、若干安全默认值偏弱、内部基础设施信息在部署/CI 清单中残留、`item_order` 已实证静默失效，以及一个会让「测试全绿」偶尔不成立的非确定性用例。这些都不是架构性难题，多为「收尾与护栏」问题，修复成本低、收益高。

**综合评分：7.5 / 10——架构优秀、业务严谨、工程意识强；补齐数据一致性与安全护栏后具备稳定的生产可用性。**

---

*本报告基于源码通读与一次真实 `pytest` 运行（96 passed / 1 failed）。运行时性能、并发与生产行为需结合线上监控数据进一步验证。*

---

## 附录 A：Hermes 独立复核（2026-10-17）

opencode 的两条关键结论已由 Hermes 用独立命令复核，**均成立**：

| 结论 | 复核方法 | 结果 |
|---|---|---|
| `item_order` 静默不落库 | 用 `TEST_DATABASE_URL=sqlite+aiosqlite:////tmp/probe.db` 复现「原地 append + commit」，新会话读回 | **确认**：读回仍是 `[]`（SQLAlchemy 普通 `JSON` 列不追踪可变对象变更） |
| `test_print_roster` 非确定性失败 | 连续跑 30 次 `pytest tests/test_print_roster.py` | **确认**：4/30 失败（13.3%），与报告估算的 ~13% 吻合。根因链路已核对：`users.py:31 _charset` 含 `&` → `users.py:181 escape(password)` → 测试 `assert temp in roster.text`（比较原始明文） |

补充事实：
- Hermes 单次全量 `pytest` 得 **97 passed, 0 failed**（未命中 `&` 分支），与 opencode 的 "96 passed / 1 failed" 不冲突——正是非确定性的体现。
- 报告 §5.2 列出的内网地址（`192.168.67.x`、`10.0.0.252`、`compassio.xyz`）确属私有部署信息；若本报告对外发布，需按既有约定隐去。
