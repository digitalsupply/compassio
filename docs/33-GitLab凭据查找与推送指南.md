# GitLab 凭据查找与推送指南

> 内网 GitLab（`192.168.67.201`）走 HTTP，推送需要认证。本文记录凭据的存储位置、查找步骤，以及免手动拼 URL 的 credential helper 配置方法。**不包含明文 token。**

## 一、背景

- GitLab 地址：`http://192.168.67.201/digitalsupply/compassio.git`（HTTPS 不可用，走 HTTP）
- 该地址需要用户名 + Token（PAT）认证；SSH 公钥未授权，`git@192.168.67.201` 返回 `Permission denied (publickey)`
- 仓库与本机默认**没有**存储任何 GitLab 凭据（无 `credential.helper`、无 `~/.git-credentials`、无 `~/.netrc`）

## 二、凭据存放位置

GitLab 的 root PAT 存放在 **k8s 集群的 `cicd/gitlab-auth` Secret** 中，含以下 key：

| Key | 含义 |
| --- | --- |
| `username` | GitLab 用户名（`ci-rw`） |
| `token` | GitLab Personal Access Token（PAT） |
| `password` | 同 token（兼容字段） |
| `git-url` | 代码仓库地址 |
| `gitops-url` | GitOps 仓库地址 |

> 该 Secret 同时被 CI/CD 链路复用：Tekton 任务拉代码、ArgoCD 同步 GitOps 仓、Webhook 管控均使用它。

## 三、从集群取用凭据（完整步骤）

```bash
# ① 确认集群可访问 + Secret 存在
kubectl get secret gitlab-auth -n cicd

# ② 查看 Secret 有哪些 key（不回显值，只确认结构）
kubectl get secret gitlab-auth -n cicd -o jsonpath='{.data}' \
  | python3 -c "import sys,json;[print(k) for k in json.load(sys.stdin)]"

# ③ 解码出 username 和 token（base64 解码）
GL_USER=$(kubectl get secret gitlab-auth -n cicd -o jsonpath='{.data.username}' | base64 -d)
GL_TOKEN=$(kubectl get secret gitlab-auth -n cicd -o jsonpath='{.data.token}' | base64 -d)

# ④ 用 token 作为密码，HTTPS 推送（一次性方式）
git push "http://${GL_USER}:${GL_TOKEN}@192.168.67.201/digitalsupply/compassio.git" main

# ⑤ 验证远端已更新（ls-remote 带凭据）
git ls-remote "http://${GL_USER}:${GL_TOKEN}@192.168.67.201/digitalsupply/compassio.git" refs/heads/main
```

**注意**：`git fetch origin` 会因为裸 HTTP URL 无凭据而失败，需按上面 ④⑤ 把凭据拼进 URL，或使用下文的 credential helper。

## 四、配置 credential helper（免每次手动拼 URL）

写一个 helper 脚本，从 k8s Secret **动态**取凭据，**不落盘明文 token**：

```bash
# ① 写脚本（路径可自定，需在 PATH 中）
cat > /usr/local/bin/git-credential-gitlab-k8s <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
action="${1:-}"
if [[ "$action" == "get" ]]; then
  user=$(kubectl get secret gitlab-auth -n cicd -o jsonpath='{.data.username}' | base64 -d)
  token=$(kubectl get secret gitlab-auth -n cicd -o jsonpath='{.data.token}' | base64 -d)
  printf 'username=%s\npassword=%s\n' "$user" "$token"
elif [[ "$action" == "store" ]]; then
  exit 0
fi
EOF
chmod +x /usr/local/bin/git-credential-gitlab-k8s

# ② 仅对该 GitLab 主机生效（不污染其他仓库）
git config --global credential."http://192.168.67.201".helper "/usr/local/bin/git-credential-gitlab-k8s"
```

配置后，`git fetch` / `git push origin` 会自动调用该 helper 从集群取凭据，无需再手动拼 URL。

**依赖**：该 helper 依赖本机 `kubectl` 能访问集群且有权限读取 `cicd/gitlab-auth`。

## 五、安全提示

- **不要**把明文 token 写进仓库、Docker 镜像或提交到任何远端。
- 本指南只记录**查找与使用方法**，不记录 token 明文值。
- 该 PAT 是 root 级（`is_admin=true`），权限较大，建议按需收窄到 `write_repository`。
