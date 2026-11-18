# Redis 缓存穿透、击穿、雪崩防护分析

> 结合 Compassio 项目源码与线上部署配置（`deploy/`），分析三种缓存风险的标准解法、项目实际落地情况，以及已做与待补强项。

## 一、三种问题的本质与标准解法

| 问题 | 本质 | 典型解法 |
| --- | --- | --- |
| **缓存穿透** | 查询一个**根本不存在**的 key，缓存和数据库都没有，每次请求都压到数据库 | 空值缓存、布隆过滤器、入口参数校验 |
| **缓存击穿** | 一个**热点 key 过期**，大量并发同时未命中，一起回源数据库 | 互斥锁/单飞、逻辑过期、热点预热 |
| **缓存雪崩** | **大批 key 同时过期**或 **Redis 整体宕机**，缓存层集体失效 | TTL 加随机抖动、Redis 高可用、多级缓存 + 降级熔断 |

## 二、项目中 Redis 的实际使用

项目中 Redis 用于三处：

1. **下一题预取缓存**（`backend/app/next_cache.py`）
   - key：`compassio:next:{assessment_id}`，TTL 300s
   - 主存储为 Redis；Redis 不可用时透明回退到**有界进程内 LRU**（`OrderedDict`，容量 500、TTL 300s）
   - 读取即消费（one-shot，读后 `delete`），由 `/answer`、`/start` 后异步预取预热
2. **登录防爆破限流**（`backend/app/ratelimit.py`）
   - 按用户名（SHA-256 哈希后存储）统计失败次数，`INCR + EXPIRE` 走同一 pipeline
   - 超过阈值返回 429 锁定，成功登录清零
3. **LLM 探活节流**（`backend/app/main.py`）
   - 探活结果与「本轮谁去探活」都放 Redis，全进程共享（uvicorn `--workers 4`）
   - 用 `SET NX EX` 抢占探活名额，避免多进程同时打 LLM 网关

## 三、逐项对照分析

### 1. 缓存穿透 —— 靠「入口校验」挡，没有空值缓存 / 布隆过滤器

`/next` 的处理顺序是关键（`backend/app/routers/assess.py:201`）：

```python
assessment = await _load_assessment(db, id, user)   # 先查库 + 鉴权，不存在直接 404
...
cached = await read_next(id)                         # 库里有，才去读缓存
```

不存在的 `assessment_id` 在碰缓存之前就被数据库校验拦掉，**根本不会进入缓存读取路径**。这是一种有效的「入口参数校验」式防穿透。

- ✅ 已做：入口校验（先查库确认 key 存在 + 鉴权，再读缓存）
- ❌ 未做：空值缓存、布隆过滤器
- 登录限流侧用户名做 SHA-256 哈希存储（`ratelimit.py:27`）属隐私处理，不构成防穿透

### 2. 缓存击穿 —— 做了「SET NX EX 互斥锁」，但仅在 LLM 探活，`/next` 重算没有

**明确做了的是 LLM 探活**（`backend/app/main.py:238`）：

```python
async def _acquire_slot(key: str, ttl: int) -> bool:
    """抢占一个跨进程名额（SET NX EX）；Redis 不可用时放行，退化为进程内节流。"""
    client = get_redis()
    if client is None:
        return True
    try:
        return bool(await client.set(key, "1", nx=True, ex=max(1, ttl)))
    except Exception:
        return True
```

多进程并发探活同一 LLM 会形成热点回源。`SET NX EX` 让**只有一个进程去探活，其余抢锁失败直接复用结果**——这是标准的互斥锁/单飞防击穿，且 Redis 不可用时放行，不会卡住探活。

**存在缺口**：`/next` 缓存未命中时，直接调用 `pick_next_item`（`assess.py:228`）重算，**没有**加单飞/互斥。若某个 assessment 预取失败、缓存为空，多个并发 `/next` 会同时回源（甚至同时打 LLM）。目前靠「预取提前预热」规避，而非互斥锁兜底。

- ✅ 已做：LLM 探活的跨进程 `SET NX EX` 互斥锁 / 单飞
- ⚠️ 缺口：`/next` 缓存未命中重算未加单飞/互斥

### 3. 缓存雪崩 —— 做了「多级缓存 + 优雅降级」，是项目里最成体系的一个

这是项目里**最明确、最刻意**做的防护，核心是「Redis 挂了也不能拖垮服务」的降级策略，体现在每一处 Redis 调用：

- **下一题缓存降级**（`next_cache.py:76-108`）：Redis 读写失败时，透明回退到有界进程内 LRU（容量 500、TTL 300s），缓存失败绝不抛给调用方。Redis 整体宕机时，预取缓存退化成进程内缓存，接口照常工作。
- **登录限流降级**（`ratelimit.py:34-46`）：Redis 不可用 → `is_login_locked` 永远返回 `False`（放行），**宁可不锁也不阻断登录**，`record_login_failure` 失败静默丢弃。
- **LLM 探活降级**（`main.py:214-246`）：Redis 不可用时，健康记录与探活名额退化为进程内节流。

线上部署侧的配合（`deploy/`）：

- Redis 配置 `allkeys-lru`、`maxmemory` 低于容器上限（k8s 中 384mb vs 512Mi），**先淘汰再 OOM**，避免 Redis 被 OOM-kill 引发雪崩。
- 监控告警（`deploy/k8s/base/04-observability.yaml`）：`CompassioRedisDown`（Redis 依赖不可用）与「预取未命中率 >50% 且确实在等 LLM」告警，能在雪崩早期发现。

**未做项**：

- TTL 没有加随机抖动（`next_cache.py:36` 为固定 300s），理论上存在同批过期风险。
- Redis 为**单实例、无 Sentinel/Cluster、appendonly no**，高可用层面偏弱——项目实际是**用「降级兜底」而非「Redis 高可用」来扛雪崩**。

- ✅ 已做：多级缓存（Redis + 进程内兜底）、优雅降级、淘汰策略、监控告警
- ❌ 未做：TTL 随机抖动、Redis 高可用（Sentinel/Cluster）

## 四、总结：项目里做了哪个

| 问题 | 项目落地情况 | 评价 |
| --- | --- | --- |
| **缓存穿透** | 入口校验（先查库校验 key 存在性再读缓存） | ⚠️ 间接做了，轻量方案；无空值缓存、无布隆 |
| **缓存击穿** | LLM 探活 `SET NX EX` 互斥锁/单飞 | ✅ 做了，但仅 LLM 探活；`/next` 重算有缺口 |
| **缓存雪崩** | 多级缓存 + 优雅降级 + 淘汰策略 + 监控告警 | ✅ 做了，最成体系的主防线 |

**主防线是「雪崩」的多级缓存 + 优雅降级**：三处 Redis 调用全部有进程内兜底，配 `allkeys-lru` 与告警。

## 五、补强优先级建议

1. **给 `/next` 缓存未命中的重算加单飞**（补击穿缺口）——并发 miss 时只放一个请求回源，其余复用结果。
2. **给 TTL 加随机抖动**（补雪崩同批过期）——在 300s 基础上叠加小幅随机，避免集中失效。
3. **评估是否需要空值缓存**（补穿透）——对高频但可能不存在的 key，缓存空值短 TTL，进一步减轻 DB 压力。
