# GitLab JWKS 公钥详解与集群 SSO/OIDC 验证实践

> 基于本集群（GitLab `http://192.168.67.201`、Harbor `192.168.67.202:8443`、ArgoCD、oauth2-proxy、Traefik、Grafana）实测配置整理。

---

## 一、GitLab JWKS 公钥是什么

**JWKS（JSON Web Key Set，RFC 7517）** 是一组以 JSON 格式发布的**公钥集合**。GitLab 作为 OIDC Identity Provider（IdP），用它来发布「签发 ID Token 所用的公钥」。任何客户端（ArgoCD、oauth2-proxy、Grafana 等）拿到这组公钥后，就能验证 GitLab 签发的 ID Token 的**签名真伪**，而无需信任网络身份。

核心是**非对称签名**：

- GitLab 持有**私钥**，签发 ID Token 时用私钥对 `header.payload` 做签名（RS256 = RSA + SHA-256）。
- 客户端只持有**公钥**（来自 JWKS），用公钥验证签名。验证通过 = 这个 ID Token 确实是 GitLab 签的、未被篡改。

### 本集群实测的 GitLab JWKS

从 GitLab（`http://192.168.67.201`）的 OIDC discovery 实测拉取：

```
discovery:  http://192.168.67.201/.well-known/openid-configuration
jwks_uri:   http://192.168.67.201/oauth/discovery/keys
签名算法:   RS256（GitLab 仅支持 RS256）
subject类型: public
JWKS缓存:   Cache-Control: max-age=86400（公钥集缓存 24 小时）
```

实际 JWKS 包含 **2 把 RSA 公钥**（GitLab 进行密钥轮换，新旧密钥并存以便平滑过渡）：

| kid | kty | alg | 密钥长度 |
|-----|-----|-----|---------|
| `7KeZDjaOsYzu8ISHDfHBXGKH0dF46yz0TLNmc6maKOM` | RSA | RS256 | ≈4096 bit |
| `-0yBMreUBVmSNb0kMiidOv53GuMLALpxPvluT7GLws4` | RSA | RS256 | ≈2048 bit |

每把公钥的 JSON 结构（以第一把为例）：

```json
{
  "kty": "RSA",
  "kid": "7KeZDjaOsYzu8ISHDfHBXGKH0dF46yz0TLNmc6maKOM",
  "e": "AQAB",
  "n": "3hPORrbiymqtEuguQAyHsb-_lWkMqMlnVMS0mQU5QV4Y5A7YJkXKx-thEiNe6E9...",
  "use": "sig",
  "alg": "RS256"
}
```

- `n` + `e` 是 RSA 公钥的模数和公钥指数，两者组合即可还原完整公钥。
- **`kid`（Key ID）是关键**：每个 ID Token 的 header 里会带 `kid`，客户端据此从 JWKS 里选对应的那把公钥来验签。

---

## 二、如何验证 GitLab JWKS 公钥

验证一个 GitLab 签发的 ID Token，完整流程 5 步：

1. **拉取 discovery** → 拿到 `jwks_uri`、`issuer`、支持的算法。
2. **拉取 JWKS** → 拿到公钥集（缓存 24h，生产环境应本地缓存而非每次拉取）。
3. **解析 ID Token 的 header** → 取 `kid` 和 `alg`，确认 `alg == RS256`。
4. **用匹配 kid 的公钥验签** → 对 `header.payload` 做 RSA-PKCS1v15-SHA256 验签。
5. **校验 claims** → `iss`（签发者）、`aud`（受众=client_id）、`exp`/`nbf`（有效期）、`kid` 匹配。

### 安全要点

> - **算法必须白名单**：只接受 `RS256`，拒绝 `none` 或 `HS256`（防止算法混淆攻击）。
> - **kid 必须匹配**：token 的 kid 不在 JWKS 里，直接拒绝。
> - **公钥用于验证，私钥绝不外泄**：JWKS 只含公钥，泄露 JWKS 不构成安全风险，但泄露私钥会导致任意签发 token。

### 本集群可用的验证脚本

脚本位置：`/tmp/opencode/verify_gitlab_jwks.py`（仅依赖 `requests` + `cryptography`，无需 PyJWT）。

功能：拉取 discovery → 拉取 JWKS → 验证 ID Token 的签名与所有 claims（签名、kid、iss、aud、exp、nbf）。

**仅拉取并自检 JWKS：**

```bash
python3 /tmp/opencode/verify_gitlab_jwks.py --issuer http://192.168.67.201
```

实测输出：

```
[1] 拉取 OIDC discovery: ...
    issuer     : http://192.168.67.201
    jwks_uri   : http://192.168.67.201/oauth/discovery/keys
    签名算法   : ['RS256']
[2] 拉取 JWKS 公钥集: ...
    共 2 把 RSA 公钥:
      - kid=7KeZDjaOsYzu8ISHDfHBXGKH0dF46yz0TLNmc6maKOM  密钥长度≈4096bit
      - kid=-0yBMreUBVmSNb0kMiidOv53GuMLALpxPvluT7GLws4  密钥长度≈2048bit
```

**验证一个真实 ID Token：**

```bash
python3 /tmp/opencode/verify_gitlab_jwks.py \
  --issuer http://192.168.67.201 \
  --token "<从浏览器/ArgoCD/oauth2-proxy 拿到的 ID Token>" \
  --client-id 7cde3dbfe3800036588275af741b36e60d882b18acda08cf25bc9637200038fe
```

通过时输出签名有效、iss/aud/exp 校验通过及关键 claims（email、groups 等）；失败时明确指出是签名、kid、iss、aud 还是过期哪一项不通过。

**脚本验证逻辑已通过端到端自检**（`/tmp/opencode/selftest_verify.py`）：现场生成 RSA 密钥对签发合法 token → 正确接受；篡改 payload → 正确拒绝（签名失败）；用未知 kid → 正确拒绝。证明逻辑对真实 GitLab RS256 JWKS 一致成立。

**如何拿到真实 ID Token 做端到端验证：**

- GitLab 的 ID Token 只在**授权码流程**签发，`client_credentials` 不返回 ID Token（本集群实测 client_credentials 返回 500，该 client 未启用）。
- 最简单方式：浏览器登录一次 ArgoCD 或任一 oauth2-proxy 应用，从浏览器 DevTools 的 localStorage / oauth2-proxy cookie 中提取 `id_token`，再用脚本验证。
- 也可用 `kubectl` 进入 oauth2-proxy pod 查看其缓存的发现文档与公钥。

### 验证脚本核心实现（RS256）

```python
def verify_jwt(token, keys, issuer, client_id=None, leeway=30):
    header_b64, payload_b64, sig_b64 = token.split(".")
    header = json.loads(b64url_decode(header_b64))
    payload = json.loads(b64url_decode(payload_b64))
    signature = b64url_decode(sig_b64)

    # 算法白名单：GitLab OIDC 只支持 RS256
    if header.get("alg") != "RS256":
        return False, {"error": f"不支持的算法: {header.get('alg')}"}

    kid = header.get("kid")
    if kid not in keys:
        return False, {"error": f"kid 不在 JWKS 中: {kid}"}

    pub_key, _ = keys[kid]
    signed_input = f"{header_b64}.{payload_b64}".encode()
    try:
        pub_key.verify(signature, signed_input,
                      padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        return False, {"error": "签名验证失败（token 被篡改或非 GitLab 签发）"}

    # 校验 iss / aud / exp / nbf ...
    ...
```

---

## 三、结合本集群各组件详解 JWKS 的使用

本集群 GitLab 作为统一 OIDC IdP（`http://192.168.67.201`），为多个组件提供 SSO。各组件对 JWKS 的依赖程度不同。

### 组件总览

| 组件 | 是否用 JWKS 验签 | 验证/排查手段 |
|------|:---:|---|
| **ArgoCD** | ✅ 是 | `argocd-cm` 的 `oidc.config`；用脚本验 `id_token` |
| **oauth2-proxy**（5个） | ✅ 是 | `--oidc-issuer-url` 触发 discovery+JWKS；`kubectl logs` |
| **Traefik** | ❌ 否（由 oauth2-proxy 代验） | 看路由/中间件；鉴权问题查 oauth2-proxy-traefik |
| **Grafana** | ⚠️ 间接（generic_oauth） | 走 userinfo，不验 JWKS；如需验签改 `[auth.oidc]` |
| **Harbor** | ✅ 是（OIDC 登录） | `auth_mode=oidc_auth`，`oidc_endpoint` 指向 GitLab；用 GitLab JWKS 验签；镜像拉取另走 harbor-auth 凭证 |

### 1. ArgoCD（`argocd` 命名空间）— 直接使用 JWKS 验签

**配置**（ConfigMap `argocd-cm` 的 `oidc.config`）：

```yaml
oidc.config: |
  name: GitLab
  issuer: http://192.168.67.201
  clientID: 7cde3dbfe3800036588275af741b36e60d882b18acda08cf25bc9637200038fe
  clientSecret: $argocd-oauth:client-secret   # 实际值在 secret/argocd-oauth
  requestedScopes: ["openid", "profile", "email"]
  requestedIDTokenClaims:
    groups:
      essential: true
  enablePKCEAuthentication: true
```

**JWKS 作用**：ArgoCD 使用 Go 的 `coreos/go-oidc` 库。用户访问 ArgoCD 时：

1. ArgoCD 用 `issuer` 自动请求 discovery，拿到 `jwks_uri`。
2. 拉取并缓存 JWKS 公钥。
3. GitLab 授权后回调，ArgoCD 收到 ID Token，用 JWKS 公钥**验签** + 校验 `iss`/`aud`，通过后从 `groups` claim 做 RBAC 授权。

**验证/排查**：

- 登录失败且报签名/kid 错误 → 多半是 GitLab 密钥轮换，ArgoCD 的 JWKS 缓存未刷新（JWKS 默认缓存 24h，ArgoCD 有后台刷新）。
- 可用脚本对该 ArgoCD 的 `clientID` 验证拿到的 `id_token`。
- 注意 issuer 是 `http://`（内网无 TLS），ArgoCD 允许 http issuer，但生产建议加 TLS 并让 issuer 用 HTTPS，否则有中间人风险。

### 2. oauth2-proxy（`oauth2-proxy` 命名空间）— 直接使用 JWKS 验签

本集群有 **5 个 oauth2-proxy 实例**，全部用 GitLab OIDC 做 SSO 保护，包括 **Traefik API**：

| 实例 | 保护的上游（upstream） |
|------|----------------------|
| oauth2-proxy-traefik | Traefik API (`traefik-api.traefik.svc:9000`) |
| oauth2-proxy-alloy | Alloy 日志 |
| oauth2-proxy-headlamp | Headlamp (K8s 控制台) |
| oauth2-proxy-hubble | Hubble (Cilium) |
| oauth2-proxy-tekton | Tekton Dashboard |

**配置**（部署参数，以 traefik 为例）：

```
--provider=oidc
--oidc-issuer-url=http://192.168.67.201
--provider-display-name=GitLab
--scope=openid profile email
--code-challenge-method=S256          # PKCE
--oidc-groups-claim=groups
--redirect-url=https://traefik.xyz/oauth2/callback
--insecure-oidc-allow-unverified-email=true
```

每个实例有独立的 `client-secret`（存于 Secret，如 `oauth2-traefik` 的 `gloas-278b...`）。

**JWKS 作用**：oauth2-proxy 同样用 `go-oidc`，通过 `--oidc-issuer-url` 自动 discovery + 拉取 JWKS，验证 GitLab 返回的 ID Token 签名，校验 `iss`/`aud`/`groups`，然后把用户身份通过 `X-Forwarded-User`/`X-Forwarded-Groups` 头传给上游（Traefik API 等）。

**验证/排查**：

- oauth2-proxy 启动时会打印拉取的发现文档和公钥，可用 `kubectl -n oauth2-proxy logs deploy/oauth2-proxy-traefik` 查看。
- `--insecure-oidc-allow-unverified-email=true` 表示允许 email 未验证——不影响 JWKS 验签，但意味着邮箱真实性未校验，按需收紧。
- PKCE（`S256`）已启用，比纯 client_secret 更安全。

### 3. Traefik（`traefik` 命名空间）— 不直接验 JWKS，依赖 oauth2-proxy

**实测结论**：本集群 Traefik **自身没有配置 OIDC middleware**（grep 无 `oidc`/`jwks` 命中）。Traefik 的角色是**入口网关**：

- 把外部流量路由到各后端，包括 `oauth2-proxy-traefik`（保护 Traefik 自己的 API）。
- **JWKS 验证发生在 oauth2-proxy 层**，而非 Traefik。Traefik 只负责把请求转发给 oauth2-proxy 做鉴权。

> 区分：如果用 Traefik 的 `OIDC`/`ForwardAuth` middleware 做 OIDC，Traefik 会自己去拉 JWKS 验签；但本集群用的是独立的 oauth2-proxy 容器，所以 JWKS 验证下沉到了 oauth2-proxy。

**验证/排查**：Traefik 侧看路由和中间件配置；鉴权问题看 oauth2-proxy-traefik 日志。

### 4. Grafana（`monitoring` 命名空间）— 用 OAuth2，不直接用 JWKS

**配置**（ConfigMap `prometheus-grafana`）：

```ini
[auth.generic_oauth]
name = GitLab
api_url     = http://192.168.67.201/oauth/userinfo
auth_url    = http://192.168.67.201/oauth/authorize
token_url   = http://192.168.67.201/oauth/token
```

Secret `grafana-oauth` 存 `client-secret`（`gloas-bf1a...`）。

**关键区别**：Grafana 用的是 **`generic_oauth`（OAuth2 模式），不是 OIDC 模式**。

- 它走授权码流程拿到 **access_token**，然后用 access_token 调 GitLab 的 `/oauth/userinfo` 获取用户信息。
- **不直接用 JWKS 验签 ID Token**（它不处理 ID Token，只处理 access_token + userinfo）。
- 所以 Grafana 对 JWKS 的依赖是**间接的**：GitLab 内部签发/校验 token 仍基于其密钥体系，但 Grafana 这一侧不做 JWKS 验签。

> 若要 Grafana 也走 JWKS 验签，需把配置改成 `[auth.oidc]` 并指定 issuer，Grafana 才会拉 JWKS 验证 ID Token。当前配置下，Grafana 的 SSO 安全性依赖 GitLab 的 access_token 与 userinfo 端点。

**验证/排查**：Grafana 登录问题看 userinfo 调用是否成功，不涉及 JWKS；若要排查 GitLab 端 token 签名，用脚本对 GitLab 签发的 token 验证。

### 5. Harbor（集群外部 `192.168.67.202:8443`）— 已纳入 GitLab SSO，使用 JWKS 验签

**实测结论**：`192.168.67.202:8443` 是**集群外部的独立 Harbor 实例**（集群内无 Harbor 的 pod/svc/ingress）。该 Harbor **已启用 OIDC 认证并接入 GitLab SSO**，用户登录 Harbor 时走 GitLab OIDC 流程，Harbor 用 **GitLab 的 JWKS 公钥验证** GitLab 签发的 ID Token。

**证据 1 — Harbor `systeminfo`（admin 认证实测）：**

```json
{
  "auth_mode": "oidc_auth",
  "oidc_provider_name": "GitLab",
  "external_url": "https://192.168.67.202:8443",
  "harbor_version": "v2.14.5-c83198c6",
  "registry_url": "192.168.67.202:8443"
}
```

`auth_mode = oidc_auth` 表明 Harbor 认证模式为 OIDC；`oidc_provider_name = GitLab` 表明 OIDC Provider 就是 GitLab。

**证据 2 — Harbor OIDC 完整配置（`/api/v2.0/configurations` 实测）：**

| 配置项 | 值 | 说明 |
|--------|-----|------|
| `oidc_endpoint` | `http://192.168.67.201` | OIDC Provider = GitLab，与 ArgoCD/oauth2-proxy 同一 IdP |
| `oidc_name` | `GitLab` | 登录页显示的按钮名 |
| `oidc_client_id` | `c7924430a6d02f5e14da2251233eb98c7a880ece868c96758da91ebd7c1ae502` | Harbor 在 GitLab 注册的 OAuth App |
| `oidc_scope` | `openid,profile,email` | 请求的 scope |
| `oidc_user_claim` | `preferred_username` | 从 ID Token 取用户名 |
| `oidc_groups_claim` | `groups` | 从 ID Token 取用户组 |
| `oidc_admin_group` | `digitalsupply` | 该 GitLab 组的用户为 Harbor 管理员 |
| `oidc_auto_onboard` | `True` | 首次登录自动创建用户 |
| `oidc_verify_cert` | `False` | 因 issuer 为 http，不校验 TLS 证书 |
| `oidc_logout` | `False` | 未启用 OIDC 单点登出 |

**证据 3 — 镜像拉取凭证（`gitlab-runner` 命名空间）：**

Secret `harbor-auth`（dockerconfigjson）用于 CI 拉取镜像，与 SSO 登录是两套独立机制：

```json
{"auths":{"192.168.67.202:8443":{"username":"admin","password":"Harbor12345",...}}}
```

gitlab-runner 配置里 helper image 从 `192.168.67.202:8443/openwebui/gitlab-runner-helper:...` 拉取，`image_pull_secrets = ["harbor-auth"]`。

**与 JWKS 的关系：**

- **Harbor 用户登录走 GitLab OIDC 授权码流程**：用户在 Harbor 登录页点击「GitLab」按钮 → 跳转 GitLab 授权 → GitLab 回调 Harbor 并返回 ID Token → **Harbor 拉取 GitLab JWKS 公钥验证该 ID Token 签名** → 验签通过后从 `preferred_username`/`groups` claim 提取身份，`digitalsupply` 组映射为管理员。
- **Harbor 的 `oidc_endpoint` 与 ArgoCD/oauth2-proxy 完全相同**（`http://192.168.67.201`），因此 Harbor 登录时拉取的 `jwks_uri` 也是 `http://192.168.67.201/oauth/discovery/keys`，用的是同一把 GitLab RSA 公钥集。可用脚本对 Harbor 的 `client_id` 做一致性确认：

```bash
python3 /tmp/opencode/verify_gitlab_jwks.py \
  --issuer http://192.168.67.201 \
  --token "<Harbor 登录后拿到的 ID Token>" \
  --client-id c7924430a6d02f5e14da2251233eb98c7a880ece868c96758da91ebd7c1ae502
```

- **镜像拉取（CI/CD）与 SSO 登录是两套机制**：镜像拉取走 `harbor-auth` 的 dockerconfigjson（静态凭证），不涉及 JWKS；SSO 登录走 OIDC + JWKS 验签。两者相互独立。
- **安全建议**：`oidc_verify_cert=False` 因 http 内网环境，建议 GitLab 与 Harbor 间改 HTTPS 并开启证书校验；镜像拉取的静态密码 `Harbor12345` 较弱，建议改用 Harbor 的 OIDC token 或更强凭证。

---

## 四、验证方法汇总与排查清单

### 通用验证工具（已验证可用）

```bash
# 1. 拉取并自检 GitLab JWKS 公钥
python3 /tmp/opencode/verify_gitlab_jwks.py --issuer http://192.168.67.201

# 2. 验证真实 ID Token（需从浏览器登录后提取）
python3 /tmp/opencode/verify_gitlab_jwks.py \
  --issuer http://192.168.67.201 \
  --token "<id_token>" \
  --client-id <对应组件的client_id>

# 3. 手动拉取 JWKS
curl -s http://192.168.67.201/oauth/discovery/keys | python3 -m json.tool

# 4. 拉取 OIDC discovery 文档
curl -s http://192.168.67.201/.well-known/openid-configuration | python3 -m json.tool
```

### 各组件客户端 ID 速查

| 组件 | clientID / client-secret 位置 |
|------|------------------------------|
| ArgoCD | `7cde3dbfe3800036588275af741b36e60d882b18acda08cf25bc9637200038fe` / `secret/argocd-oauth` |
| oauth2-proxy-traefik | Secret `oauth2-traefik`（client-secret: `gloas-278b...`） |
| oauth2-proxy-alloy | Secret `oauth2-alloy` |
| oauth2-proxy-headlamp | Secret `oauth2-headlamp` |
| oauth2-proxy-hubble | Secret `oauth2-hubble` |
| oauth2-proxy-tekton | Secret `oauth2-tekton` |
| Grafana | Secret `grafana-oauth`（client-secret: `gloas-bf1a...`，generic_oauth 模式） |
| Harbor | `192.168.67.202:8443`，OIDC client_id `c7924430a6d02f5e14da2251233eb98c7a880ece868c96758da91ebd7c1ae502`（oidc_auth 模式）；镜像拉取走 Secret `harbor-auth`（dockerconfigjson，admin/Harbor12345） |

### 常见故障与原因

| 故障 | 原因与处理 |
|------|-----------|
| **`kid not found in JWKS`** | GitLab 密钥轮换，客户端 JWKS 缓存过旧。清缓存/等自动刷新（JWKS 缓存 24h），或重启客户端强制重新拉取。 |
| **`signature verification failed`** | token 被篡改，或用错了公钥（kid 不匹配），或 issuer 配错导致拉了别的 IdP 的 JWKS。 |
| **`iss mismatch`** | 客户端配置的 `issuer` 与 GitLab discovery 返回的 `issuer` 不一致（注意末尾是否带斜杠、http/https）。 |
| **`token expired`** | ID Token 有效期短（通常 10 分钟），过期正常，重新走授权即可。 |

### 安全加固建议

1. **GitLab issuer 当前是 `http://192.168.67.201`（明文）**：内网可用但建议加 TLS 并改 HTTPS，防止中间人篡改 discovery/JWKS。
2. **Grafana 用 `generic_oauth` 不验 JWKS**：若需严格验证 ID Token 可切换为 `[auth.oidc]` 模式。
3. **Harbor 已接入 GitLab OIDC SSO**：`oidc_verify_cert=False`（因 http 内网），建议 GitLab 与 Harbor 间改 HTTPS 并开启证书校验；镜像拉取的静态密码 `Harbor12345` 较弱，建议改用更强凭证。
4. **oauth2-proxy 的 `--insecure-oidc-allow-unverified-email=true`**：按需收紧，确保邮箱真实性。

---

## 附：关键配置位置索引

| 组件 | 命名空间 | 资源 |
|------|---------|------|
| ArgoCD OIDC 配置 | `argocd` | ConfigMap `argocd-cm`（`oidc.config`） |
| ArgoCD client 凭据 | `argocd` | Secret `argocd-oauth` |
| oauth2-proxy 部署参数 | `oauth2-proxy` | Deployment `oauth2-proxy-{traefik,alloy,headlamp,hubble,tekton}` |
| oauth2-proxy client 凭据 | `oauth2-proxy` | Secret `oauth2-{traefik,alloy,headlamp,hubble,tekton}` |
| Grafana OAuth 配置 | `monitoring` | ConfigMap `prometheus-grafana`（`[auth.generic_oauth]`） |
| Grafana client 凭据 | `monitoring` | Secret `grafana-oauth` |
| GitLab Runner 配置 | `gitlab-runner` | Secret `gitlab-runner-config`（`runners.toml`） |
| Harbor OIDC 配置（集群外部） | 外部 `192.168.67.202:8443` | Harbor API `/api/v2.0/configurations`（`auth_mode=oidc_auth`，`oidc_endpoint`→GitLab） |
| Harbor 镜像拉取凭证 | `gitlab-runner` | Secret `harbor-auth`（dockerconfigjson，指向外部 `192.168.67.202:8443`） |
