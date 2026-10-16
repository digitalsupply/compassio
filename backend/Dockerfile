FROM python:3.11-slim

WORKDIR /app

# 安全基线（Harbor/Trivy）：切国内源后把基础镜像里的 OS 包升到 bookworm 当前安全版本。
# 可由此消除：openssl/libssl3 3.0.15 → 3.0.20-1~deb12u2、libgnutls30 → 3.7.9-2+deb12u7、
# perl-base → 5.36.0-7+deb12u3、krb5 / libpcre2 / gpgv / libcap2 等。
# Debian 明确未修复的（util-linux 2.38.1-5+deb12u3、zlib1g 等）无法用版本升级解决。
RUN export DEBIAN_FRONTEND=noninteractive; \
    sed -i "s|deb.debian.org|mirrors.aliyun.com|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    sed -i "s|deb.debian.org|mirrors.aliyun.com|g" /etc/apt/sources.list 2>/dev/null; \
    apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# 基础镜像自带的 pip/setuptools/wheel 版本偏旧（Harbor 报了 setuptools CVE-2024-6345 /
# CVE-2025-47273 / CVE-2026-59890、wheel CVE-2026-24049、pip 多个 CVE），先升到当前版本。
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
