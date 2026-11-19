# Redis 在本项目中的使用详解（功能、问题、命令、代码案例）

> 本文以 Compassio 项目实际代码与线上部署为基础，详解 Redis 在本项目中承担的**三项功能**、**解决的问题**、**具体代码案例**、**运维命令**与**用法步骤**，并保留缓存穿透/击穿/雪崩的防护分析。所有命令与代码均可对照仓库与集群复现。

## 一、Redis 在本项目的定位

Redis 在本项目中是**可选的共享状态与缓存中间件**，承担三类功能，贯穿"性能优化、安全防护、依赖探活"三条线：

| 场景 | 代码文件 | Redis 的角色 | 核心键 | 解决的问题 |
| --- | --- | --- | --- | --- |
| 下一题预取缓存 | `app/next_cache.py` | 跨进程共享缓存 | `compassio:next:{assessment_id}` | 消除 `/next` 的同步 LLM 往返，把延迟从秒级压到 <20ms |
| 登录防爆破限流 | `app/ratelimit.py` | 跨进程计数器 | `compassio:login:fail:{哈希用户名}` | 防止撞库/爆破，失败达阈值锁定账号 |
| LLM 探活节流 | `app/main.py` | 跨进程健康记录 + 互斥锁 | `compassio:deps:llm*` | 多 worker 共享探活结果，避免重复打 LLM 网关、浪费额度 |

**设计原则**：Redis 是**可选增强**，不可用时全部优雅降级，绝不阻断业务。这一点贯穿三处实现——每处 Redis 调用失败都有进程内兜底或放行策略。

**连接配置**（`app/config.py:26`）：

```python
redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
```

**连接获取**（`app/db.py:79-86`，懒加载单例，失败返回 None 不抛错）：

```python
def get_redis() -> redis.Redis | None:
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(get_settings().redis_url, decode_responses=True)
        except Exception:
            return None
    return _redis_client
```

> `decode_responses=True` 让返回值直接是字符串，无需手动解码。

## 二、Redis 引入解决的三类问题

### 2.1 性能问题：`/next` 的同步 LLM 延迟

**原问题**：每次 `GET /next` 都要同步调用 LLM 选下一题，单次 2–5 秒，用户等待久、LLM 额度消耗大。

**Redis 解法**：在用户答完一题（`/answer`）或开始评估（`/start`）后，**异步预取**下一题并缓存。后续 `/next` 直接读缓存返回，<20ms 出结果。缓存由 Redis 承载，**多 worker 进程共享**（uvicorn 多 worker 场景下，进程内缓存会"各说各话"，必须用 Redis 共享）。

### 2.2 安全问题：登录爆破/撞库

**原问题**：登录接口可被无限次尝试，攻击者可暴力破解密码。

**Redis 解法**：按用户名统计失败次数，达到阈值后锁定一段时间（返回 429）。用 Redis 承载计数器，**多副本/多 worker 共享计数**，且用户名哈希后存储（不落明文账号标识）。

### 2.3 成本与稳定性问题：LLM 探活重复调用

**原问题**：`/api/health` 与 30s 后台任务要探活 LLM 依赖。多 worker 并发探活会重复打 LLM 网关，推理模型单次 2–5s 拖累探针，还浪费付费额度。

**Redis 解法**：探活结果与"本轮谁去探活"都放 Redis，**全集群共享**——每个间隔只有一个 worker 真正探活，其余直接复用结果。用 `SET NX EX` 实现跨进程互斥锁（单飞）。

## 三、部署与配置

**容器部署**（`deploy/compose/docker-compose.yml`）：

```yaml
redis:
  image: redis:7-alpine
  command: ["redis-server", "--maxmemory", "512mb", "--maxmemory-policy", "allkeys-lru"]
  restart: unless-stopped
backend:
  environment:
    REDIS_URL: redis://redis:6379/0
```

**K8s 部署**（`deploy/k8s/base/01-namespace-postgres-redis.yaml`）：

```yaml
- name: redis
  image: redis:7-alpine
  args:
    - redis-server
    - --maxmemory
    - 384mb            # 低于容器内存上限(512Mi)，先淘汰再 OOM
    - --maxmemory-policy
    - allkeys-lru
    - --appendonly
    - "no"
```

**要点**：
- **单实例**，无 Sentinel/Cluster；
- `allkeys-lru`：内存满时按 LRU 淘汰，避免 OOM-kill；
- `appendonly no`：不持久化，作为缓存/计数场景，重启丢缓存可接受（业务有降级兜底）。

## 四、场景一：下一题预取缓存

### 4.1 功能与流程

```
用户答完题(/answer) 或 开始(/start)
        │
        ▼
schedule_prefetch() 异步计算下一题
        │
        ▼
write_next() → 写 Redis(TTL 300s)
        │
        ▼
用户点 下一题(/next)
        │
        ▼
read_next() → 读 Redis(读后即删，一次性消费) → <20ms 返回
```

**核心设计**：缓存是**预取 + 一次性消费**——读完即 `delete`，避免同一题被重复消费；TTL 300s 兜底过期。

### 4.2 代码案例（`app/next_cache.py`）

**写入**（`write_next`，Redis 失败回退进程内缓存）：

```python
async def write_next(assessment_id: int, payload: dict) -> str:
    key = cache_key(assessment_id)                      # compassio:next:{id}
    body = json.dumps(payload, ensure_ascii=False)
    client = get_redis()
    if client is not None:
        try:
            await client.set(key, body, ex=TTL_SECONDS)  # TTL 300s
            inc_next_cache("prefetch_written")
            return "redis"
        except Exception:
            logger.warning("next-cache redis write failed; using local fallback")
    _local_set(key, payload)   # 降级：进程内有界 LRU(500)
    return "local"
```

**读取**（`read_next`，读后删除，一次性消费）：

```python
async def read_next(assessment_id: int) -> dict | None:
    key = cache_key(assessment_id)
    client = get_redis()
    if client is not None:
        try:
            raw = await client.get(key)
            if raw:
                await client.delete(key)   # 读后即删
                inc_next_cache("hit")
                return json.loads(raw)
        except Exception:
            logger.warning("next-cache redis read failed; using local fallback")
    payload = _local_pop(key)               # 降级：进程内 LRU
    ...
    return None
```

**调用处**（`app/routers/assess.py` 的 `/next`）：

```python
cached = await read_next(id)               # 先读缓存
if cached is not None:
    ...                                     # 命中直接用
if not used_cache:
    chosen, transition, ... = await pick_next_item(...)   # 未命中才回源 LLM
```

### 4.3 运维命令

```bash
# 进入 Redis（k8s）
kubectl -n compassio exec -it deploy/compassio-redis -- redis-cli

# 查看某评估的预取缓存
redis-cli GET "compassio:next:42"

# 查看所有 next 键（排查预取是否写入）
redis-cli --scan --pattern "compassio:next:*"

# 查看缓存统计（命中/未命中，来自应用指标 compassio_next_cache_total）
# Grafana 面板：下一题预取缓存（命中/未命中/写入）
```

### 4.4 用法步骤

1. **确认预取开启**：环境变量 `PREFETCH_ENABLED=true`（默认开）；
2. **观察指标**：Grafana 看 `compassio_next_cache_total` 的 `hit`/`miss`/`prefetch_written`；
3. **排查未命中**：`redis-cli --scan --pattern "compassio:next:*"` 看是否有键；无键说明预取未写入（检查 `prefetch_error` 指标与后端日志）；
4. **验证命中**：`GET compassio:next:{id}` 有值，说明预取正常，`/next` 走缓存。

## 五、场景二：登录防爆破限流

### 5.1 功能与流程

```
登录请求 → is_login_locked(username)?
            │ 是 → 直接 429，不查库（避免用"是否200"判定密码对错）
            │ 否 → 查库校验密码
            │     失败 → record_login_failure() 计数+1，返回 401
            │     成功 → clear_login_failures() 清零，返回 token
```

**核心设计**：用户名 SHA-256 哈希后作为键，不存明文账号；`INCR + EXPIRE` 走同一 pipeline，避免"INCR 成功、EXPIRE 失败留下无 TTL 的键"导致永久锁定。

### 5.2 代码案例（`app/ratelimit.py` + `app/routers/auth.py`）

**键生成**（哈希用户名）：

```python
def _key(username: str) -> str:
    digest = hashlib.sha256((username or "").strip().lower().encode("utf-8")).hexdigest()
    return f"{KEY_PREFIX}{digest}"          # compassio:login:fail:{sha256}
```

**计数**（`record_login_failure`，pipeline 保证原子性）：

```python
async def record_login_failure(username: str) -> None:
    client = get_redis()
    if client is None:
        return
    key = _key(username)
    pipe = client.pipeline()
    pipe.incr(key)                       # 计数 +1
    pipe.expire(key, max(1, get_settings().login_rate_limit_window_seconds))  # 刷新 TTL
    await pipe.execute()                 # 同一事务，避免无 TTL 残留
```

**判定锁定**（`is_login_locked`，Redis 不可用 → 永远放行）：

```python
async def is_login_locked(username: str) -> bool:
    client = get_redis()
    if client is None:
        return False                     # Redis 挂了也不阻断登录
    ...
    return int(raw) >= max(1, get_settings().login_rate_limit_attempts)
```

**调用处**（`app/routers/auth.py`）：

```python
if await is_login_locked(payload.username):
    raise HTTPException(status_code=429, detail="登录失败次数过多，请稍后再试",
                        headers={"Retry-After": str(...)})
result = await db.execute(select(User).where(User.username == payload.username))
if user is None or not verify_password(...):
    await record_login_failure(payload.username)   # 失败计数
    raise HTTPException(status_code=401, ...)
await clear_login_failures(payload.username)        # 成功清零
```

### 5.3 运维命令

```bash
# 查看某用户失败计数（用户名需先 SHA-256 哈希）
echo -n "stu_noredis" | sha256sum
redis-cli GET "compassio:login:fail:<sha256值>"

# 手动清零某用户计数（用户找回密码后）
redis-cli DEL "compassio:login:fail:<sha256值>"

# 查看所有被锁定的计数键
redis-cli --scan --pattern "compassio:login:fail:*"

# 统计当前锁定用户数
redis-cli --scan --pattern "compassio:login:fail:*" | wc -l

# 查看键的 TTL（确认是否有残留无 TTL 键）
redis-cli TTL "compassio:login:fail:<sha256值>"
```

### 5.4 用法步骤

1. **确认参数**：`LOGIN_RATE_LIMIT_ATTEMPTS`（默认 10）、`LOGIN_RATE_LIMIT_WINDOW_SECONDS`（默认 300）；
2. **模拟爆破**：对某用户名连续用错密码登录 10 次，第 11 次应返回 429；
3. **排查计数**：`GET compassio:login:fail:<哈希>` 看当前计数与 TTL；
4. **解锁**：用户正确登录自动清零；或运维 `DEL` 手动清零。

## 六、场景三：LLM 探活节流

### 6.1 功能与流程

```
/api/health 或 30s 后台任务 → _maybe_llm_check()
    │
    ├─ _shared_llm_health() 读 Redis 健康值
    │     有新鲜值 → 直接复用，不探活
    │
    └─ 无值 → _acquire_slot() 用 SET NX EX 抢探活名额
              抢到 → 探活 → 结果写回 Redis
              没抢到 → 等别的 worker 探活，直接复用
```

**核心设计**：探活结果（`compassio:deps:llm`）+ 探活名额（`compassio:deps:llm:probe`）都放 Redis，多 worker 共享，每个间隔只探活一次。`SET NX EX` 是跨进程互斥锁（防击穿）。

### 6.2 代码案例（`app/main.py`）

**互斥锁（`_acquire_slot`，SET NX EX）**：

```python
async def _acquire_slot(key: str, ttl: int) -> bool:
    """抢占一个跨进程名额（SET NX EX）；Redis 不可用时放行。"""
    client = get_redis()
    if client is None:
        return True
    try:
        return bool(await client.set(key, "1", nx=True, ex=max(1, ttl)))
    except Exception:
        return True
```

**读/写共享健康值**：

```python
async def _shared_llm_health() -> bool | None:
    client = get_redis()
    if client is None:
        return None
    raw = await client.get(LLM_HEALTH_KEY)      # compassio:deps:llm
    return None if raw is None else raw == "1"

async def _store_shared_llm_health(ok: bool, ttl: int) -> None:
    client = get_redis()
    if client is None or ttl <= 0:
        return
    await client.set(LLM_HEALTH_KEY, "1" if ok else "0", ex=ttl)
```

**节流调用**（`_maybe_llm_check`，抢不到名额直接复用）：

```python
shared = await _shared_llm_health()
if shared is not None:
    return shared                       # 有新鲜值，所有 worker 同答案
if not await _acquire_slot(LLM_PROBE_LOCK_KEY, LLM_PROBE_SLOT_SECONDS):
    return None                         # 别的 worker 在探活，本机不重复
ok = await _probe_llm_reachable(provider)
await _store_shared_llm_health(ok, _LAST_LLM_CHECK_TTL)
```

### 6.3 运维命令

```bash
# 查看当前 LLM 健康值
redis-cli GET "compassio:deps:llm"

# 查看探活名额锁（非空说明正有 worker 在探活）
redis-cli GET "compassio:deps:llm:probe"
redis-cli TTL "compassio:deps:llm:probe"

# 手动清除探活锁（探活卡住时强制重置）
redis-cli DEL "compassio:deps:llm:probe"
redis-cli DEL "compassio:deps:llm:ping"

# 查看所有依赖相关键
redis-cli --scan --pattern "compassio:deps:*"
```

### 6.4 用法步骤

1. **观察健康**：`/api/health` 或 Grafana `compassio_dependency_up{dependency="llm"}` 看 LLM 状态；
2. **排查重复探活**：同时看 `compassio:deps:llm:probe` 锁与后端日志，确认是否每个间隔只探活一次；
3. **探活卡住**：若锁长期不释放（TTL 异常），`DEL` 锁强制重置，让下个间隔重新探活；
4. **调间隔**：改 `LLM_REACHABILITY_INTERVAL_SECONDS` / `LLM_PING_INTERVAL_SECONDS`（0=关闭）。

## 七、通用运维命令

```bash
# 进入 Redis（k8s）
kubectl -n compassio exec -it deploy/compassio-redis -- redis-cli

# 基础检查
redis-cli PING                       # 应返回 PONG
redis-cli INFO memory | grep -E "used_memory_human|maxmemory_human|mem_allocator"
redis-cli INFO keyspace              # 各 DB 键数量
redis-cli DBSIZE                     # 当前 DB 键总数

# 键扫描（按模式，排查三类场景）
redis-cli --scan --pattern "compassio:next:*"          # 预取缓存
redis-cli --scan --pattern "compassio:login:fail:*"   # 登录计数
redis-cli --scan --pattern "compassio:deps:*"         # LLM 探活

# 键详情
redis-cli TTL <key>                  # 剩余 TTL（-1=无TTL，-2=不存在）
redis-cli TYPE <key>                 # 类型
redis-cli STRLEN <key>               # 字符串长度

# 内存与淘汰
redis-cli CONFIG GET maxmemory       # 内存上限
redis-cli CONFIG GET maxmemory-policy # 淘汰策略
redis-cli INFO eviction              # 淘汰统计

# 慢日志
redis-cli SLOWLOG GET 10             # 最近 10 条慢命令

# 清空（慎用！会清掉所有业务缓存/计数）
redis-cli FLUSHDB                    # 清当前 DB
```

## 八、故障与降级

**核心原则：Redis 不可用时，三处功能全部优雅降级，绝不阻断业务。**

| 场景 | Redis 不可用时的行为 | 代码依据 |
| --- | --- | --- |
| 预取缓存 | 回退进程内有界 LRU（500 条，TTL 300s），接口照常 | `next_cache.py` `_local_set`/`_local_pop` |
| 登录限流 | `is_login_locked` 永远返回 False，**宁可不锁也不阻断登录** | `ratelimit.py:37` |
| LLM 探活 | 健康值与名额退化为进程内节流 | `main.py` `_LLM_HEALTH` |

**监控告警**（`deploy/k8s/base/04-observability.yaml`）：
- `CompassioRedisDown`：`compassio_dependency_up{dependency="redis"} == 0`，Redis 不可用告警；
- 预取未命中率 >50% 且确实在等 LLM 时告警（单纯 miss 不告警，规则兜底是正常）。

**排查 Redis 故障**：
```bash
kubectl -n compassio get pods -l app=compassio-redis      # Pod 是否存活
kubectl -n compassio logs deploy/compassio-redis          # 日志
kubectl -n compassio exec deploy/compassio-redis -- redis-cli PING   # 连通性
kubectl -n compassio exec deploy/compassio-redis -- redis-cli INFO memory
```

## 九、缓存穿透、击穿、雪崩防护

在三处实现的基础上，本项目对三类缓存风险的防护如下。

### 9.1 缓存穿透 —— 入口校验挡，无空值缓存/布隆

`/next` 的处理顺序（`app/routers/assess.py:201`）：**先查库校验 assessment 存在 + 鉴权，再读缓存**。不存在的 `assessment_id` 在碰缓存前就被拦掉，不进入缓存读取路径。

- ✅ 已做：入口校验（先查库确认 key 存在再读缓存）
- ❌ 未做：空值缓存、布隆过滤器

### 9.2 缓存击穿 —— LLM 探活有 SET NX EX 互斥，`/next` 重算无

**已做**：LLM 探活的 `_acquire_slot`（`SET NX EX`），多 worker 只让一个探活，其余复用——标准互斥锁/单飞。

**缺口**：`/next` 缓存未命中时直接调 `pick_next_item`（`assess.py:228`）重算，**未加单飞**。若某 assessment 预取失败、缓存为空，多个并发 `/next` 会同时回源（甚至打 LLM）。目前靠预取预热规避。

### 9.3 缓存雪崩 —— 多级缓存 + 优雅降级（最成体系）

**主防线**。三处 Redis 调用全部有进程内兜底降级：
- 预取缓存 → 进程内 LRU；
- 登录限流 → 放行（不锁）；
- LLM 探活 → 进程内节流。

配合部署侧：`allkeys-lru` + `maxmemory` 低于容器上限（先淘汰再 OOM）、`CompassioRedisDown` 告警。

**未做**：TTL 无随机抖动（固定 300s，理论同批过期风险）；Redis 单实例无高可用——实际是**用降级兜底而非 Redis 高可用扛雪崩**。

## 十、总结

| 维度 | 说明 |
| --- | --- |
| **三项功能** | 预取缓存（性能）、登录限流（安全）、LLM 探活节流（成本/稳定） |
| **解决的问题** | `/next` 秒级延迟 → <20ms；登录爆破；LLM 探活重复调用 |
| **代码核心** | `next_cache.py`、`ratelimit.py`、`main.py`，均带 Redis 失败降级 |
| **运维要点** | `redis-cli` 按模式扫描键、查 TTL/计数/健康值、SLOWLOG、INFO |
| **降级原则** | Redis 不可用时全部优雅降级，不阻断业务，配 `CompassioRedisDown` 告警 |
| **三防现状** | 穿透靠入口校验；击穿 LLM 探活有互斥、`/next` 有缺口；雪崩靠多级缓存+降级 |

> 一句话：Redis 在 Compassio 是"可选的共享状态层"，承担缓存、计数、互斥三件事，核心价值是**多 worker 共享 + 失败降级**；运维上以键模式扫描 + 指标告警为主，三防以雪崩的多级降级最成体系。
