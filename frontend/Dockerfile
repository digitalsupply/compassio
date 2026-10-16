# 多阶段构建：node 构建静态文件 → nginx 托管
# 安全基线（Harbor/Trivy）：两个阶段都切 aliyun 的 alpine 源并把 apk 包升到当前安全版本。
# 可由此消除：libcrypto3/libssl3 3.3.2-r1 → 3.3.7-r0、libxml2 2.12.7 → 2.12.10、
# libpng、libexpat、libxslt、musl、xz-libs、zlib 等；node 18 已 EOL，升到 node 22。
FROM node:22-alpine AS builder
WORKDIR /app
RUN sed -i 's|dl-cdn.alpinelinux.org|mirrors.aliyun.com|g' /etc/apk/repositories && \
    apk upgrade --no-cache
COPY package*.json ./
RUN npm install --registry=https://registry.npmmirror.com
COPY . .
RUN npm run build

FROM nginx:alpine
RUN sed -i 's|dl-cdn.alpinelinux.org|mirrors.aliyun.com|g' /etc/apk/repositories && \
    apk upgrade --no-cache
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
