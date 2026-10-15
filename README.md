<div align="center">

# 🧭 Compassio

**Heart Education Compass for Schools**

*Guide early. Grow strong.* — **提前指引，向阳成长。**

一个由大模型驱动的校级心理健康测评系统：
既是指引方向的**罗盘**，也是带着关怀去守护成长的陪伴。

> 我们不贴标签、不制造焦虑。每一次测评，都只是一次温柔地看见自己。

</div>

---

## 它能做什么

| 角色 | 能做的事 |
|---|---|
| **校级管理员** | 导入师生名单 → 自动生成账号与初始密码（可打印下发）→ 查看班级完成率与预警通知 → 按班级把学生结果分发给班主任 |
| **班主任（教师）** | 收到分发后查看本班学生的筛查结果（可打印）；本人也可做教师自评 |
| **学生** | 登录后选择适合学段的量表作答，全程单题呈现、可断点续答；作答情况由大模型实时调整出题节奏；完成后看到自己的报告与结论 |
| **教师本人** | 填写教师量表 — **结果仅本人可见，任何管理员不可见** |

## 三套测评量表

| 量表 | 对象 | 结构 | 计分 |
|---|---|---|---|
| **MHT 心理健康诊断测验** | 小学四年级至高中 | 100 题：8 个内容量表（学习焦虑/对人焦虑/孤独/自责/过敏/身体症状/恐怖/冲动）+ 效度量表（测谎 10 题，≥7 作废） | 是=1 否=0；总分≤55 正常 / 56–64 欠佳 / ≥65 重点 |
| **MSSMHS 中国中学生心理健康量表** | 初中/高中 | 60 题 × 10 维度（强迫/偏执/敌对/人际敏感/抑郁/焦虑/学习压力/适应/情绪波动/心理不平衡） | 1–5 分；因子分≥2 提示问题，≥3 中度及以上 |
| **教师心理健康评价量表（参考版）** | 教师 | 60 题 × 4 维度（自我/社会/工作/生活），6 点计分 | 分数越高心理健康资源越充分 |

> ⚠️ 教师量表当前为**自编参考版**（结构参照俞国良等 2010 公开文献），非原版量表、信效度未经检验，仅作发展性自我觉察。获得原版题目后，管理员在后台上传新 JSON 即可热替换，系统无需改代码。

## 大模型的角色（安全边界）

- ✅ **实时调整出题**：根据已答情况动态选择下一题（高风险维度优先探查、保证覆盖与效度题必答）
- ✅ **生成测评结论**：筛查语言（非诊断）、正向框架、可执行建议 + 关怀语；失败时自动回退到模板结论
- ✅ **极端预警**：命中危机题（如 MHT 85/97、MSSMHS 30）→ **第一批时间**通知校级管理员（站内中心，可扩展企业微信/webhook）
- 🚫 **绝不参与计分**：计分是纯确定性引擎，严格按量表 JSON 定义
- 🚫 **教师预警不通知任何人**：只作为自我关怀提示呈现给教师本人

## LLM 支持

统一 OpenAI 兼容抽象，预置（管理员界面可配、可自测连通性）：

`opencode-go`（默认）/ `deepseek` / `qwen`（阿里百炼）/ `zhipu`（智谱 GLM）/ `openrouter` / `volcano`（火山方舟）/ `kimi`（月之暗面）/ `ollama`（本地）/ `custom`（任意 OpenAI 兼容端点）

> 项目实测默认通路：`https://opencode.ai/inference/go/v1` + `deepseek-v4.1-flash`，网关要求每次请求携带 `x-opencode-session` 头（系统已自动处理）。

## 架构

```
┌──────────────┐   ┌───────────────────┐   ┌────────────────────┐
│ Vue3 + TS +  │──▶│ FastAPI (async)   │──▶│ PostgreSQL (CNPG)  │
│ Element Plus │   │ uvicorn×workers │   │ Redis (会话/限流)  │
│ ECharts 雷达 │   │ JWT + RBAC        │   └────────────────────┘
└──────────────┘   │ LLM 抽象 (httpx)  │──▶ openai-compatible 网关
   nginx 托管       └───────────────────┘
```

代码同仓库双部署形态：

- **传统部署**：`deploy/compose/docker-compose.yml`（Postgres + Redis + backend + frontend nginx，4 条命令起）
- **集群部署**：`deploy/k8s`（kustomize：CNPG PG、Redis、双 Deployment、Traefik Ingress `compassio.xyz`）

## 快速开始

### 传统（compose）

```bash
cd deploy/compose
cp .env.example .env      # 编辑密码/LLM key
docker compose up -d
# 访问 http://<主机>/
```

首次启动自动建表并装载题目库。管理员账号：`admin / Compassio@2026`（**上线后立即改**）。

### 集群（GitOps 全自动）

本仓库代码 push 会自动：GitLab webhook → Tekton Pipeline（BuildKit 构建 backend/frontend 双镜像）→ Harbor（自动漏洞扫描）→ `compassio-gitops` 仓库 bump image tag → ArgoCD 自动同步 → Traefik 暴露 `http://compassio.xyz`（用户在访问侧绑定 hosts 指向 LB `10.0.0.252`）。

手动同步：`argocd app sync compassio`

## 命令速查

| 场景 | 命令 |
|---|---|
| 本地跑后端测试 | `cd backend && python -m pytest -q` |
| 本地前端构建 | `cd frontend && npm install && npm run build` |
| 看 CI 进度 | `kubectl get pipelineruns -n cicd | grep compassio` |
| 看 Harbor 扫描 | Harbor UI → 项目 compassio → 制品 → 扫描报告 |
| 重置某师生密码 | 管理后台 → 账号管理 → 重置密码 |
| 替换教师量表题库 | 管理后台 → 题目库管理 → teacher_ref → 上传新 JSON |

## 着重声明

- 所有结果属于**发展性筛查参考**，不构成医学诊断；高分提示联系学校心理老师或专业机构
- 学生心理健康数据按班级最小化分发给班主任；教师数据仅本人可见；系统保留审计日志
- Pipeline 中 LLM 超时/失败均自动回退，不影响可用性

## 技术文档

- [`SPEC.md`](SPEC.md) — 完整技术规格（施工图：数据模型/权限矩阵/自适应算法/LLM 抽象/部署）
- [`docs/01-全过程实录.md`](docs/01-全过程实录.md) — 本次交付全过程、配置细节与注意事项
- [`docs/02-CI-CD运维手册.md`](docs/02-CI-CD运维手册.md) — Tekton/Harbor/GitOps/ArgoCD/隧道运维手册
