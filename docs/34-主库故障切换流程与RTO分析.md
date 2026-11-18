# 主库故障切换流程与 RTO 分析

> 结合 Compassio 项目实际部署（CNPG `pg16-ceph` 集群）与后端连接池配置，分析主库宕机时的切换流程、RTO，以及风险与加固项。

## 一、主库架构现状

主库由 **CloudNativePG（CNPG）** 管理，是 1 主 1 从的高可用集群，非单机：

| 项 | 当前实际值 |
| --- | --- |
| 集群 | `cnpg-system/pg16-ceph`，2 实例 |
| 当前主库 | `pg16-ceph-3`（worker03） |
| 副本 | `pg16-ceph-4`（worker02） |
| 复制方式 | streaming，**异步**（`maxSyncReplicas=0`、`minSyncReplicas=0`） |
| 当前复制延迟 | `lag_bytes = 0`（已追平） |
| 切换方法 | `primaryUpdateMethod=switchover` |
| 更新策略 | `primaryUpdateStrategy=unsupervised`（Operator 自动处理） |
| 应用接入 | Service `pg16-ceph-rw.cnpg-system.svc:5432`（自动指向主库） |

**实证**：运维手册（2026-10-27 写）记录主库为 `pg16-ceph-4`，当前实际主库已是 `pg16-ceph-3`——期间发生过一次真实故障切换，集群已恢复 `Cluster in healthy state`。这是线上跑过的实证，非纸面方案。

## 二、切换流程

### 2.1 非计划故障切换（主库宕机，Operator 自动）

CNPG Operator 自动完成，分四步：

1. **检测**：Operator 探测主库 Pod / PostgreSQL 健康，判定主库不可用。
2. **选主提升**：Operator 从副本中选 **WAL 最全（追得最先进）的副本**提升为新主库。当前仅 1 副本，直接提升 `pg16-ceph-4`。
3. **服务切换**：CNPG 自动把读写 Service `pg16-ceph-rw` 的 Endpoints 指向新主库。**应用无需改连接串**——应用一直连的是 Service，不是 Pod IP。
4. **应用侧恢复**：后端连接池中**指向旧主库的存量连接变为坏连接**，需等它们出错被池丢弃、再重连到新主库。

### 2.2 计划内切换（维护窗口，人工主动）

用 `kubectl cnpg promote` 主动执行，走 `switchover`（优雅切换，不丢数据），与故障切换是两条路径：

```bash
kubectl cnpg promote pg16-ceph pg16-ceph-4 -n cnpg-system
```

计划内切换前，应先确认主库位置，避免误删主库 Pod 触发不可控 failover。

## 三、RTO 分析

需分**数据库层**和**应用层**两段看，本项目后端连接池有一个配置缺口会拉长应用侧恢复。

### 3.1 数据库层 RTO：约 30–90 秒

CNPG Operator 检测 + 提升副本 + Service 重指，典型 **30 秒到 1.5 分钟**。全程自动，无需人工介入。

### 3.2 应用层恢复：有短暂报错窗口

后端 SQLAlchemy 引擎配置在 `backend/app/db.py:22`：

```python
return create_async_engine(url, **kwargs)   # 只传了 future=True
```

**未配置 `pool_pre_ping` 与 `pool_recycle`**。意味着：

- 切换发生时，4 个 worker 进程连接池中**指向旧主库的连接不会主动失效**，要等下一次查询用到时报错，才会被丢弃并重连到新主库。
- 切换瞬间到连接池排空期间，存在**短暂报错**，每个 worker 在遇到坏连接时逐步恢复。

运维手册也明确记录：*"切换后应用连接池可能持有坏连接，必要时 `rollout restart` backend"*。若坏连接排空慢，人工重启 backend 可立即清空池、快速恢复。

### 3.3 综合 RTO

| 层级 | 恢复时间 | 说明 |
| --- | --- | --- |
| 数据库层（Operator 自动切换） | ~30–90s | 自动，无需人工 |
| 应用层（连接池自然排空） | 数秒～数十秒 | 依赖查询触发坏连接失败，**有短暂报错窗口** |
| 应用层（若 `rollout restart`） | ~1–2 分钟 | 立即清池，恢复确定性高 |

**综合有效 RTO 约 1–2 分钟**：数据库层秒级自动切换，应用层因缺 `pool_pre_ping` 存在短暂报错过渡期。

## 四、风险与加固

### 4.1 RPO > 0（异步复制）

`maxSyncReplicas=0` 为异步复制，主库宕机瞬间**可能丢失最后一个未同步的事务**。当前延迟为 0，稳态下几乎无影响，但突发宕机不等于零丢失。

- 若业务要求 RPO=0：改同步复制（`minSyncReplicas=1`），代价是写入延迟上升，需评估。

### 4.2 连接池配置缺口（当前最值得做的加固）

给引擎加上 `pool_pre_ping` 和 `pool_recycle`，让应用在切换后**主动探测坏连接**，将应用侧恢复从"等报错"变为"主动重连"，显著缩短报错窗口、让 RTO 更可控：

```python
return create_async_engine(
    url,
    future=True,
    pool_pre_ping=True,        # 借出前探测，坏连接主动剔除
    pool_recycle=300,          # 定期回收，避免长连接失效
    pool_size=5,
    max_overflow=10,
)
```

### 4.3 切换后验证

```bash
# 确认主库位置
kubectl get cluster pg16-ceph -n cnpg-system \
  -o jsonpath='{.status.currentPrimary}{"\n"}'

# 确认 rw Service 指向新主
kubectl get endpoints pg16-ceph-rw -n cnpg-system

# 确认复制状态
kubectl exec -n cnpg-system <新主Pod> -c postgres -- \
  psql -U postgres -c "select client_addr, state, sync_state from pg_stat_replication;"

# 必要时重启 backend 清空连接池
kubectl rollout restart deploy/compassio-backend -n compassio
```

## 五、一句话总结

> Compassio 主库由 CNPG 管理，1 主 1 从、异步复制。主库宕机时 Operator 自动选主提升并重指 Service，**数据库层 RTO 约 30–90 秒**；因后端未配 `pool_pre_ping`，应用侧有短暂报错窗口，**综合有效 RTO 约 1–2 分钟**。当前最值得做的加固是给引擎加 `pool_pre_ping` / `pool_recycle`，让应用主动探测坏连接、缩短恢复时间。
