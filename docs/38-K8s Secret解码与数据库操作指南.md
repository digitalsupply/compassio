# K8s Secret 解码与数据库操作指南

> 以 Compassio 的 `compassio-db-credentials` Secret 为例，详解 k8s Secret 的存储机制（base64 编码 vs 加密）、解码过程、后端数据库连接凭据获取方式，以及常用数据库操作命令。

## 一、k8s Secret 的存储机制：base64 编码，不是加密

常见误区：看到 Secret 里 `data` 字段是一串"密文"，以为是加密。**实际是 base64 编码，不是加密。**

| 层面 | 机制 | 作用 |
| --- | --- | --- |
| **git 仓库** | SealedSecret（用公钥**加密**） | 防止密码明文/密文泄露进 git |
| **集群运行时** | 普通 Secret，`data` 字段是 **base64 编码** | k8s Secret 的存储格式 |

**关键区别**：

- **base64 是编码，不是加密**——可逆、无密钥，任何人拿到都能 `base64 -d` 还原明文；
- **加密是不可逆**——没有密钥无法还原。

k8s 原生 Secret 在 etcd 里存的就是 **base64 编码后的明文**（除非集群开启了 `EncryptionConfiguration` 用 KMS 加密 etcd 落盘数据，但 `kubectl get secret` 看到的仍是 base64）。**集群内任何有权限查看 Secret 的人，都能解码看到明文密码**——这正是要收紧 Secret 的 RBAC 访问权限的原因。

**sealed-secret 的完整链路**：

```
git 里的 SealedSecret（加密）
    ↓ 集群 Controller 用私钥解密
普通 Secret（data 字段仍是 base64 编码）
    ↓
kubectl get secret 看到的 base64 值
```

**解密发生在集群内，所以集群里看到的必然是 base64。**

## 二、解码过程

以 `compassio-db-credentials` Secret 为例：

```bash
# 方式一：手动对 base64 值解码
echo "Y29tcGFzc2lv" | base64 -d                           # → compassio
echo "ZTRhYzg4ODA4YjIzOTBlNjAwOTA0NGIwNWJiNDExOTFjNjZlNGMwZWYyODNjMDQ1" | base64 -d

# 方式二：直接从 Secret 取出并解码（推荐，不用手动复制 base64）
kubectl get secret compassio-db-credentials -n compassio \
  -o jsonpath='{.data.username}' | base64 -d
kubectl get secret compassio-db-credentials -n compassio \
  -o jsonpath='{.data.password}' | base64 -d
```

解码结果：

| 字段 | 解码后 |
| --- | --- |
| username | `compassio` |
| password | `<从 Secret 解码获取，见下方连接方式>` |

> **安全说明**：本文不写明文密码进文档。生产密码不应进 git，需要时从 Secret 动态取。

## 三、获取后端数据库连接凭据

后端连接串存放在 `compassio-app-secrets` 的 `DATABASE_URL` 中，结构为：

```
postgresql+asyncpg://<user>:<password>@<host>:<port>/<database>
```

**从 Secret 取连接串（脱敏查看结构）**：

```bash
kubectl get secret compassio-app-secrets -n compassio \
  -o jsonpath='{.data.DATABASE_URL}' | base64 -d | sed -E 's#(://[^:]+):[^@]+@#\1:***@#'
```

**本项目实际连接信息**：

| 项 | 值 |
| --- | --- |
| 用户名 | `compassio` |
| 库名 | `compassio` |
| 连接地址 | `pg16-ceph-rw.cnpg-system.svc:5432` |
| 密码 | 从 `compassio-db-credentials` Secret 解码获取 |

**取密码变量（后续命令复用，避免明文写进命令）**：

```bash
PASS=$(kubectl get secret compassio-db-credentials -n compassio -o jsonpath='{.data.password}' | base64 -d)
POD=$(kubectl -n cnpg-system get cluster pg16-ceph -o jsonpath='{.status.currentPrimary}')
```

## 四、常用数据库操作命令

> 原则：密码从 Secret 取，不写进命令行明文、不进 git、不贴日志。

### 4.1 连接数据库

```bash
# 在主库 Pod 内连库（交互式）
kubectl -n cnpg-system exec -it "$POD" -c postgres -- \
  env PGPASSWORD="$PASS" psql -h 127.0.0.1 -U compassio -d compassio

# 非交互式执行单条 SQL
kubectl -n cnpg-system exec "$POD" -c postgres -- \
  env PGPASSWORD="$PASS" psql -h 127.0.0.1 -U compassio -d compassio -c "select 1;"

# 本地 port-forward 直连
kubectl -n cnpg-system port-forward svc/pg16-ceph-rw 5432:5432
# 然后本地：psql -h 127.0.0.1 -U compassio -d compassio
```

### 4.2 基本信息查询

```bash
kubectl -n cnpg-system exec "$POD" -c postgres -- \
  env PGPASSWORD="$PASS" psql -h 127.0.0.1 -U compassio -d compassio -c "
select current_user, current_database(), version();
"
# 在 psql 内：\l+ 列出所有库及大小；\dt 列出表；\dt+ 表+大小
```

### 4.3 查数据

```bash
# 用户表
kubectl -n cnpg-system exec "$POD" -c postgres -- \
  env PGPASSWORD="$PASS" psql -h 127.0.0.1 -U compassio -d compassio -c "
select id, username, role, created_at from public.users order by id desc limit 20;
"

# 评估作答记录
kubectl -n cnpg-system exec "$POD" -c postgres -- \
  env PGPASSWORD="$PASS" psql -h 127.0.0.1 -U compassio -d compassio -c "
select assessment_id, item_id, value, answered_at
from public.responses order by answered_at desc limit 20;
"

# 估算行数（避免大表 count(*) 扫全表）
kubectl -n cnpg-system exec "$POD" -c postgres -- \
  env PGPASSWORD="$PASS" psql -h 127.0.0.1 -U compassio -d compassio -c "
select relname, n_live_tup, n_dead_tup from pg_stat_user_tables
order by n_live_tup desc;
"
```

### 4.4 连接与性能排查

```bash
# 连接数分布
kubectl -n cnpg-system exec "$POD" -c postgres -- \
  env PGPASSWORD="$PASS" psql -h 127.0.0.1 -U compassio -d compassio -c "
select usename, state, count(*) from pg_stat_activity
where datname = current_database() group by 1,2 order by 3 desc;
"

# 长事务（占用连接不释放）
kubectl -n cnpg-system exec "$POD" -c postgres -- \
  env PGPASSWORD="$PASS" psql -h 127.0.0.1 -U compassio -d compassio -c "
select pid, now()-xact_start as age, left(query,80) as query
from pg_stat_activity where xact_start is not null and now()-xact_start > interval '1 min';
"

# 锁等待
kubectl -n cnpg-system exec "$POD" -c postgres -- \
  env PGPASSWORD="$PASS" psql -h 127.0.0.1 -U compassio -d compassio -c "
select pid, pg_blocking_pids(pid) as blockers, wait_event_type, left(query,80)
from pg_stat_activity where wait_event_type='Lock';
"
```

### 4.5 复制与高可用

```bash
# 复制延迟（主库视角）
kubectl -n cnpg-system exec "$POD" -c postgres -- \
  env PGPASSWORD="$PASS" psql -h 127.0.0.1 -U compassio -d compassio -c "
select client_addr, state, sync_state,
       pg_wal_lsn_diff(sent_lsn, replay_lsn) as lag_bytes
from pg_stat_replication;
"

# 集群状态与主库位置
kubectl -n cnpg-system get cluster pg16-ceph \
  -o jsonpath='{.status.phase}{"  primary="}{.status.currentPrimary}{"\n"}'
kubectl -n cnpg-system get pods -l cnpg.io/cluster=pg16-ceph \
  -o custom-columns='POD:.metadata.name,ROLE:.metadata.labels.cnpg\.io/instanceRole,READY:.status.containerStatuses[0].ready'
```

### 4.6 备份与恢复

```bash
# 逻辑备份（主库内执行）
kubectl -n cnpg-system exec "$POD" -c postgres -- \
  env PGPASSWORD="$PASS" pg_dump -h 127.0.0.1 -U compassio -d compassio -Fc \
  > /tmp/compassio-$(date +%Y%m%d-%H%M%S).dump

# 查看 CNPG 管理的备份
kubectl -n cnpg-system get backup,scheduledbackup

# 手动触发备份
cat <<EOF | kubectl -n cnpg-system apply -f -
apiVersion: postgresql.cnpg.io/v1
kind: Backup
metadata:
  name: pg16-ceph-manual-$(date +%Y%m%d%H%M)
spec:
  cluster:
    name: pg16-ceph
EOF
```

### 4.7 RBAC 安全审计

```bash
# 查看相关 Secret（确认存在，注意不要外泄解码值）
kubectl get secret compassio-db-credentials -n compassio
kubectl get secret compassio-app-secrets -n compassio

# 检查谁有权限查看 Secret（RBAC 审计）
kubectl -n compassio get rolebinding,clusterrolebinding | grep -i secret
```

## 五、安全要点

1. **base64 不是加密**：能看 Secret 的人就能拿到明文密码——务必收紧 RBAC，限制能 `get secrets` 的账号；
2. **密码不进 git / 命令行 / 日志**：需要时从 Secret 动态取，用变量传递（`PGPASSWORD="$PASS"`）；
3. **生产建议开启 etcd 加密**：配置 `EncryptionConfiguration`，让 Secret 在 etcd 落盘时也是加密的，防止 etcd 数据泄露后密码裸奔；
4. **最小权限**：应用只用 `compassio` 业务角色，不要用 `postgres` 超级用户做日常操作。
