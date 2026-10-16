# Compassio 项目技术规格（SPEC）

> **Compassio — Heart Education Compass for Schools**
> 口号：Guide early. Grow strong. / 提前指引，向阳成长。
> 定位：既是指引方向的"罗盘"，也是带着关怀去守护成长——**不贴标签、不制造焦虑**。

本文件是唯一施工图。实现中出现本文件未覆盖的细节，按"最简可维护"原则自行决策并在 PR 说明中记录；不得改变已定义的行为契约。

## 0. 已定事实（不要重新决策）

| 项 | 值 |
|---|---|
| 域名 | compassio.xyz（HTTP:80，用户自行绑 hosts → 10.0.0.252） |
| LLM 默认 | provider `opencode-go`，model `deepseek-v4.1-flash`，base_url `https://opencode.ai/inference/go/v1` |
| LLM 网关特殊头 | 必须发送 `x-opencode-session: <每次会话随机串>`（缺该头返回 400 MissingSessionID） |
| 通知渠道（一期） | 仅站内通知中心（前端 5s 轮询，critical 告警需在管理员页面顶部红色横幅+声音提示）；架构预留 webhook 扩展 |
| 教师量表 | 参考版（`teacher_ref.json`，`is_reference: true`），题目库 JSON 可热替换，不改代码 |
| 教师结果隐私 | **硬规则**：任何接口/查询/导出/统计都不得向 school_admin 暴露教师个人测评内容；预警不通知管理员 |
| 题目库 | `backend/app/scales/data/{mht,mssmhs,teacher_ref}.json` 已就位，**禁止修改这三个文件** |
| 部署 | 双模式：docker-compose（传统）+ K8s kustomize（CNPG PostgreSQL + Redis + Deployment + Traefik Ingress） |

## 1. 技术栈

- **后端**：Python 3.11+ / FastAPI（async）/ SQLAlchemy 2.0 async + asyncpg / Alembic / Pydantic v2 / passlib[bcrypt] / python-jose[cryptography]（JWT）/ httpx / openpyxl（Excel 导入）/ redis（aioredis 不用，用 redis-py 的 asyncio）
- **前端**：Vue 3 + Vite + TypeScript + Element Plus + Pinia + Vue Router；打印用浏览器原生打印（`@media print` 样式），不引入 PDF 库
- **数据库**：PostgreSQL 16（集群用 CNPG；compose 用官方 postgres:16 镜像）
- **并发目标**：单校 ≤3000 账号、峰值 300 人同时作答；uvicorn 多 worker、DB 连接池 ≥20、作答写路径全部轻量（单行 upsert）

## 2. 目录结构（monorepo）

```
compassio/
├── SPEC.md                    # 本文件
├── README.md                  # 品牌化 README（罗盘叙事）
├── backend/
│   ├── app/
│   │   ├── scales/data/*.json # 题目库（已就位，勿改）
│   │   ├── main.py            # FastAPI 入口 + lifespan
│   │   ├── config.py          # Pydantic Settings（env 驱动）
│   │   ├── db.py              # engine/session
│   │   ├── models.py          # SQLAlchemy ORM
│   │   ├── schemas.py         # Pydantic DTO
│   │   ├── security.py        # JWT/bcrypt/RBAC 依赖
│   │   ├── routers/           # auth, import, users, assess, notify, report, admin
│   │   ├── engine/
│   │   │   ├── scoring.py     # 确定性计分引擎（读 JSON 规则）
│   │   │   ├── adaptive.py    # LLM 自适应出题引擎（含规则回退）
│   │   │   └── risk.py        # risk_rules 实时评估
│   │   └── llm/
│   │       ├── provider.py    # OpenAI 兼容抽象 + extra_headers
│   │       └── presets.py     # 8 家预置 provider
│   ├── tests/                 # pytest（计分/预警/权限隔离必须覆盖）
│   ├── alembic/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/{views,api,stores,router}/
│   ├── Dockerfile             # 多阶段：build → nginx 托管
│   └── nginx.conf             # /api 反代到 backend
├── deploy/
│   ├── compose/docker-compose.yml
│   └── k8s/{base,overlays/prod}/   # kustomize
└── docs/                      # 交付文档（CI/CD、运维、注意事项）
```

## 3. 数据模型（SQLAlchemy）

- `users`: id, role(school_admin|teacher|student), username(唯一), password_hash, initial_password(初始密码明文，仅供管理员打印/下发名单；账号本人自助改密后清空), must_change_password(bool，历史兼容字段；系统不再强制改密，当前恒 false), real_name, gender, phone(教师可空), class_id(学生=所在班级；教师=所属班级), is_homeroom(教师是否该班班主任，学生恒 false), is_active, created_at
- `classes`: id, name(规范格式如"七年级(1)班"), grade_level(primary_g4|junior|senior), head_teacher_id(=班主任 user id)。班级与班主任的对应关系由 `classes.head_teacher_id` 与教师行的 `(class_id, is_homeroom)` 共同保证，同名教师靠班级区分。
- `scale_defs`: id, scale_id(mht|mssmhs|teacher_ref), payload(JSONB=整份题目库 JSON), version, loaded_at —— 启动时若空自动从 data/*.json 装载；提供管理员"重新导入题目库"端点（支持上传新 JSON 替换，用于教师量表日后换原版）
- `assessments`: id, user_id, scale_id, status(in_progress|completed), started_at, completed_at, item_order(JSONB: 实际出题顺序), is_valid(效度是否通过), invalidated_reason
- `responses`: id, assessment_id, item_id, value(int), answered_at；唯一约束 (assessment_id, item_id)
- `results`: id, assessment_id(unique), scores(JSONB: 各维度分/总分/效度分/评级), risk_flags(JSONB), llm_summary(text, LLM 生成的结论), fallback_used(bool), created_at
- `notifications`: id, recipient_role(school_admin), severity(info|high|critical), title, body, ref_student_id, read(bool), created_at —— **教师预警不进此表**
- `llm_configs`: id, name, provider_key, base_url, api_key, model, extra_headers(JSONB), is_active, timeout_s, is_default —— 管理员可 CRUD；DB 无配置时回退 env 默认
- `audit_logs`: id, actor_id, action, detail(JSONB), created_at

## 4. 权限矩阵（RBAC，security.py 强制依赖注入）

| 能力 | school_admin | teacher | student |
|---|---|---|---|
| 导入师生/生成账号/重置密码/查看账号名单 | ✓ | ✗ | ✗ |
| 学生结果（本校） | ✓ | 仅本班（收到分发后） | 仅本人 |
| 教师结果 | **✗（任何接口不存在）** | 仅本人 | ✗ |
| 通知中心（critical/high） | ✓ | ✗ | ✗ |
| LLM 配置管理 | ✓ | ✗ | ✗ |
| 学生可选量表 | — | — | MHT(小学四年级+)；MHT 或 MSSMHS(中学生，自选其一) |
| 教师可测量表 | — | teacher_ref | ✗（学生账号访问教师量表 → 403） |

- 量表准入按 `scale.audience` 与用户 `grade_level` 双重判定；学生不能填教师量表、教师不能填学生量表（403）。
- 教师结果 API：`GET /api/assess/my-results` 仅返回本人；不存在任何 admin 侧教师结果端点；`results` 查询在 ORM 层强制 `user_id == current_user.id` 过滤（teacher role 时）。

## 5. API 端点（REST，全部 /api 前缀）

auth: `POST /auth/login`（返回 JWT + role）、`POST /auth/change-password`
import: `GET /import/template/{kind}`(下载 csv/xlsx 模板)、`POST /import/{teachers|students}`(multipart, xlsx/csv)、`POST /import/{kind}/commit`(校验通过后真正建号)
users: `GET /admin/accounts?role=&class=&q=`(分页)、`POST /admin/accounts/{id}/reset-password`、`POST /admin/accounts/reset-passwords` {role?,class_id?,q?,password?}(按筛选批量重置为统一密码，默认 Compassio@2026，始终排除管理员)、`GET /admin/accounts/print-roster?role=&class_id=`(可打印 HTML，含初始密码、按班级分组)
assess: `GET /assess/scales`(可用量表列表)、`POST /assess/start` {scale_id}、`GET /assess/{id}/next`（自适应下一题）、`POST /assess/{id}/answer` {item_id,value}、`POST /assess/{id}/finish`、`GET /assess/my-results`、`GET /assess/{id}/report`(打印视图数据)
admin/report: `GET /admin/reports/classes`(班级汇总：完成率/各维度均值/预警数——不含教师)、`POST /admin/reports/dispatch` {class_id}(把该班学生结果分发给班主任)、`GET /teacher/class-students-results`(班主任查本班)
notify: `GET /notify/list?unread=`、`POST /notify/{id}/read`、`GET /notify/unread-count`
llm: `GET/POST/PUT/DELETE /admin/llm-configs`、`POST /admin/llm-configs/{id}/test`(发一条真实 ping)
scales: `GET /admin/scales`(当前题目库版本)、`POST /admin/scales/{scale_id}/reload`(上传替换 JSON)

## 6. 测评引擎

### 6.1 计分（engine/scoring.py，纯确定性，禁 LLM 参与）

按题目库 JSON 定义实现：
- MHT：是=1/不是=0；8 维度求和；效度量表(10题)求和 ≥7 → `is_valid=false`；总分=90 非效度题求和；bands: ≤55 normal / 56-64 subthreshold / ≥65 high；单维度三级分级（≤3 normal / 4-7 mild / ≥8 high，输出 `level`+`level_label`），≥8 同时记维度关注。
- MSSMHS：1-5 分；因子分=维度均分；≥2 轻度、≥3 中度及以上；总均分 ≥2 提示整体问题。
- teacher_ref：reverse 题 7-raw；因子分与总均分方向=越高越健康；bands 按 JSON。

### 6.2 LLM 自适应（engine/adaptive.py）

目标：**依据作答情况实时调整下一题**，同时保证计分完整性，并控制 LLM 成本。

**策略（`ADAPTIVE_STRATEGY`，默认 `fusion`）**：
- `fusion`（生产默认）：**规则负责每一题的选题**；LLM 每 **12~20 题随机一个检查点**参与一次（全局重排 + 过渡语）。一份 100 题 MHT 的 LLM 调用从 ~84 次降到 **5~8 次**（实测见 docs/07）。
- `adaptive`：每题都调 LLM（旧行为，成本最高，仅调试用）。
- `rules_only`：完全不调 LLM（零 API 成本）。
- 相关参数：`ADAPTIVE_LLM_INTERVAL_MIN=12`、`ADAPTIVE_LLM_INTERVAL_MAX=20`、`LLM_PICK_TOP_N=20`。
- 检查点调度器按测评持久化（Redis `compassio:llm_sched:{assessment_id}`，TTL 2h；Redis 不可用降级进程内缓存），同一测评可复现。
- 预取（`POST /answer` 后异步预算下一题）与融合策略叠加：LLM 调用发生在预取任务里，**学生侧无等待**。

算法（CAT-lite 两阶段）：
1. **覆盖阶段**：每个 subscale 先顺序抽 2 题（保证广度采样；效度量表题始终全部作答）——**任何策略下都不调用 LLM**，返回 `source="rule_coverage"`。
2. **加权阶段**：剩余题目按维度动态权重排序：当前维度均分越接近预警阈值权重越高（风险维度优先探查）；同维度内按题号顺序；返回 `source="rule_weighted"`；仅检查点返回 `source="llm_fusion"`。
3. LLM 角色（`fusion` 下仅在检查点调用；`adaptive` 下每题调用；非必需成功）：
   - 输入：维度当前得分概况（不传题干原文，脱敏+省 token）、候选题集（默认前 20 个，只给 id 与所属维度）；
   - 输出 JSON：`{"ordered_ids": [候选集子集], "transition": "一句不超过20字的过渡关怀语（可选）"}`（兼容旧的单题 `item_id` 形态）；
   - 约束：item_id 必须来自候选集，否则回退规则排序第一题；LLM 只能**选题与说过渡语**，不能改题目文本、不能跳过效度题、不能减少总题量（100/60/60 题全部作答后才 finish）。
4. **回退**：LLM 超时(>8s)/失败/返回非法 → 直接用规则排序下一题，`fallback_used` 计数（结果里记录自适应回退比例）。
5. `item_order` 存实际出题顺序，报告可回放。

### 6.3 预警（engine/risk.py，每次 answer 提交后同步评估）

- 通用规则引擎：按 JSON `risk_rules` 定义执行（`any_items_equal`/`any_items_gte`/`total_score_gte`/`subscale_mean_gte`/`subscales_mean_gte_3_count`/`validity_score_gte`/`total_mean_lte`）。
- severity=critical 命中 → 立即写 `notifications`（school_admin 角色，含学生姓名/班级/量表/命中规则，**不含题目原文**）+ results.risk_flags。
- severity=high → results.risk_flags + 通知。
- teacher_ref 的 risk 仅写 results.risk_flags（自我关怀提示，报告页呈现给本人），**永不写 notifications**。

### 6.4 结论生成（finish 时）

- LLM 输入：维度得分 JSON + 评级 + 预警标记（**不含逐题原文**，隐私最小化）。
- Prompt 原则（写死在代码里）：非诊断语言（"筛查结果提示…建议…"）；正向框架；给出 1-2 条可执行建议；出现 high/critical 时建议联系心理老师；结尾一句"这不是标签，只是一次看见自己的机会"风格的关怀语；120-200 字。
- 确定性锚定：分量表/总分等级由 scoring 层判定（`level`/`level_label`）并随 JSON 传入 prompt，LLM 仅负责措辞、不得改判严重程度；模板结论复用同一套 label。
- LLM 失败 → 模板结论（按评级+预警维度的确定性文案拼接），`fallback_used=true`。
- teacher_ref 结论同样生成，但更强调自我关怀与求助渠道，绝不出现"问题/障碍"字眼。

## 7. LLM Provider 抽象（llm/provider.py + presets.py）

统一 OpenAI 兼容 `POST {base_url}/chat/completions`，httpx.AsyncClient，支持：
- `extra_headers`（JSONB，opencode-go 必带 `x-opencode-session`，值=每次请求随机 uuid）
- 超时与重试（1 次重试）；响应兼容 `reasoning_content` 字段存在与否
- 测试连通端点（ping）

预置 presets（`presets.py`，写死元数据，key 由用户填）：

| key | base_url | 默认 model | 备注 |
|---|---|---|---|
| opencode-go | https://opencode.ai/inference/go/v1 | deepseek-v4.1-flash | 需 x-opencode-session 头 |
| deepseek | https://api.deepseek.com/v1 | deepseek-chat | |
| qwen | https://dashscope.aliyuncs.com/compatible-mode/v1 | qwen-plus | 阿里百炼兼容模式 |
| zhipu | https://open.bigmodel.cn/api/paas/v4 | glm-4-flash | 智谱 |
| openrouter | https://openrouter.ai/api/v1 | deepseek/deepseek-chat | |
| volcano | https://ark.cn-volces.com/api/v3 | 火山方舟（用户填 endpoint id 或 model） | 字节 |
| kimi | https://api.moonshot.cn/v1 | moonshot-v1-8k | |
| ollama | http://host:11434/v1 | 用户填 | 本地 |
| custom | 用户填 | 用户填 | 任意 OpenAI 兼容 |

env 默认（config.py）：`LLM_PROVIDER=opencode-go`、`LLM_BASE_URL=…`、`LLM_API_KEY`、`LLM_MODEL=deepseek-v4.1-flash`；DB `llm_configs` 有 default 时优先生效。

## 8. 导入与账号

- 教师 xlsx/csv 列：`姓名,手机号,性别,班级,是否班主任`（是否班主任填 是/否；标记为班主任者其班级自动写入 `classes.head_teacher_id`，同名教师按班级区分）；学生：`姓名,班级,性别,班主任`（班主任列填手机号或姓名，先按手机号、再按同班姓名匹配；留空则沿用该班已登记的班主任）。
- 班级名统一为 "七年级(1)班" 格式，兼容旧写法（初一(3)班→七年级(3)班、全角括号转半角）。
- 校验：班级不存在自动创建（grade_level 从班级名推断：含"小"或一~六年级 → primary；七/八/九年级或"初"→junior；"高"→senior；推断不出 → junior 默认并标记 warning）；重复用户名策略：重名自动加序号；行级错误全部收集一次返回（不半途失败）。
- 用户名规则：学生 `s{班级编号序}{姓名拼音小写无分隔}`，教师 `t{姓名拼音}`；拼音转换用 `pypinyin`。
- 初始密码：8 位随机（数字+大小写+符号排除易混淆字符）；写入 `users.initial_password`（明文，供管理员打印/下发）；**系统不强制首次改密**，本人可在页头「修改密码」自助改密（改密后清空 `initial_password`）。
- 账号管理「打印名单」按班级分组（同一班级师生相邻，班内教师在前、学生按姓名在后，无班级账号排最后），列为 姓名/用户名/密码/班级（不再显示角色与是否班主任）；密码列取 `initial_password`，已自行改密者显示"已修改"。
- 账号管理支持按当前筛选（班级/角色/关键词）**批量重置密码**为统一密码（默认 `Compassio@2026`，可自定义，至少 8 位）：重置后 `initial_password=统一密码`，便于一次性打印下发（**不强制改密**）；**始终排除管理员账号**，避免管理员被锁。所有被重置账号共用同一份 bcrypt 哈希（明文相同，避免 900+ 账号逐个哈希拖慢）。
- commit 返回可打印名单（HTML 表格，`@media print`），管理员可批量打印下发。
- 多工作表 xlsx 按工作表名匹配导入类型（含 `教师/teacher` 或 `学生/student`），匹配不到才退回活动表；教师性别列可留空，记"未知"（学生仍必填）。
- **导入非幂等**：同一份表重复导入会生成带序号后缀的重复账号（如 `s23baihexiang2`），重复前先清理（见 `docs/02-CI-CD运维手册.md` 第七节）。
- 批量导入性能：bcrypt 轮数由 `BCRYPT_ROUNDS` 控制（默认 10，887 人实测 ≈1分45秒）；nginx 前端已放宽 `proxy_read_timeout/send_timeout=600s`、`client_max_body_size=20m`。新增列走启动时 `_apply_light_migrations`（`ADD COLUMN IF NOT EXISTS`），无需手工迁移。

## 9. 前端页面

- 首页 Landing（`/`，公开）：未登录时展示「Compassio · 心育罗盘」品牌首页——系统简介、核心优势、三套量表、适用角色与登录 CTA；已登录访问时按角色分流到各自首页。
- 登录：登录成功后按角色进入对应首页（**系统不强制首次改密**；用户可在页头「修改密码」自助改密）。
- 学生：首页（可用量表+学段限制提示）、作答页（单题呈现、进度条、LLM 过渡语气泡、支持断点续答）、我的报告（雷达图用 ECharts、评级、结论、打印按钮）
- 教师：我的测评（teacher_ref）、我的报告（仅本人）、本班学生结果（收到分发后）
- 管理员：导入（模板下载/上传/校验结果/commit）、账号管理（查询/重置密码/批量重置为统一密码/打印名单）、通知中心（未读红点+critical 顶部红色横幅+提示音）、班级报告（完成率/维度均值/预警名单）、分发结果给班主任、LLM 配置（表单+测试按钮）、题目库管理（版本查看/替换上传）
- 路由守卫：以「token + 合法角色」判定会话；token 存在但角色缺失/非法时清理脏会话（避免首页↔守卫死循环卡在"正在跳转…"）；未登录访问受保护路由跳登录；越权路由回各自首页；未知路径兜底回首页；登录/改密接口的 401 不回跳整页。
- 全站：Compassio 品牌（罗盘 logo 用 CSS/SVG 简笔）、口号"提前指引，向阳成长"、页脚免责声明："本系统结果属于发展性筛查参考，不构成医学诊断"

## 10. 部署

### 10.1 compose（传统）
`deploy/compose/docker-compose.yml`：postgres:16、redis:7、backend（uvicorn --workers 4）、frontend（nginx:alpine 托管 dist 并反代 /api→backend:8000）、环境变量在 `.env.example`。提供 `Makefile` 或 `deploy/compose/README.md` 一键说明。

### 10.2 K8s（kustomize）
- base：Namespace compassio、Deployment backend（副本 2，liveness/readiness /api/health）、Deployment frontend、Service×2、Redis（单副本 Deployment+PVC 或 emptyDir+缓存语义即可）、CNPG Cluster（compassio-pg，instances 1，storage 10Gi storageClass 由 overlay 注入）、Secret（DB url/JWT secret/LLM env——占位，overlay 用 sealed/普通 Secret）、Ingress（traefik class，host compassio.xyz，HTTP 80）
- overlays/prod：replicas、storageClassName=csi-rbd（集群已有 ceph-csi-rbd）、镜像 tag newTag 由 CI 更新（kustomize images transformers）、资源 requests/limits
- 健康检查端点：`GET /api/health` 返回 db/redis/llm 连通状态

## 11. 测试（pytest，必须真实通过）

- scoring：三个量表各 ≥3 个用例（含效度作废、reverse 反转、bands 边界）
- risk：critical 触发（MHT 85=1）、MSSMHS 30≥3、效度作废、teacher 不写 notifications
- 权限：student 访问 teacher_ref → 403；teacher 访问其他教师结果 → 403/404；admin 无教师结果端点（路由断言）
- adaptive：LLM 失败回退顺序出题；候选集约束；过渡语缺失不阻塞
- auth：登录/改密/JWT 过期
- 跑法：`cd backend && python -m pytest -q`（DB 用 sqlite+aiosqlite 测试配置或 testcontainers 简化为 sqlite；JSONB 字段在 sqlite 降级为 JSON 文本——models 里用 sa.JSON 配 variant）

## 12. 验收（Definition of Done）

1. `pytest` 全绿；2. compose 模式 `docker compose up` 后脚本冒烟通过（登录→导入2师生→作答3题→finish→报告→通知）；3. 前端 build 无错误；4. `GET /api/health` 三依赖全通；5. 教师结果在任何 admin 响应中不可见（测试断言）；6. LLM 真实调用一次成功（opencode-go/deepseek-v4.1-flash）。

## 13. 禁止事项

- 修改 `scales/data/*.json`
- 引入 LangChain/Celery/Kafka 等重依赖（用 httpx + FastAPI BackgroundTasks + 轮询足够）
- 教师结果任何形式泄漏给 admin
- LLM 参与计分
- 前端引入重型图表库以外的 UI 框架（Element Plus + ECharts 已定）
