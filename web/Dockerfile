# FlawScope 前端容器：构建静态产物 + nginx 托管并反代 API。
#
# 为什么用两阶段构建：
#   第一阶段需要 node（编译 TS/打包），第二阶段只需要 nginx。
#   合并成单阶段会把 node_modules（数百 MB）带进最终镜像，
#   而它对运行时毫无用处。

# ---------- 阶段一：构建 ----------
FROM node:22-alpine AS builder

WORKDIR /build

# 先只拷依赖清单：只要依赖没变，这一层就能命中缓存，
# 不必每次改源码都重装一遍 node_modules。
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY . .
RUN npm run build


# ---------- 阶段二：运行 ----------
FROM nginx:1.27-alpine

# 移除默认站点配置，用我们自己的
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/flawscope.conf

# 拷入构建产物
COPY --from=builder /build/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
  CMD wget -qO- http://localhost/ >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]
