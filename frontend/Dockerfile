# syntax=docker/dockerfile:1
#
# Corporate Readiness Plan, Phase 1 (see docs/CORPORATE_READINESS_PLAN.md).
# Builds the Vite/React frontend into a static bundle served by nginx.
# `npm run dev` (see README "Setup") keeps working exactly as before --
# this is an additional, opt-in path.
#
# Vite bakes VITE_* env vars in at build time, and the built JS runs in the
# viewer's browser (not inside this container), so VITE_API_BASE must be a
# URL reachable from wherever the browser is, not an in-network hostname:
#   docker build -f frontend/Dockerfile --build-arg VITE_API_BASE=http://localhost:8000 .

FROM node:22-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_API_BASE=http://localhost:8000
ENV VITE_API_BASE=${VITE_API_BASE}
RUN npm run build

FROM nginx:1.27-alpine AS runtime

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q --spider http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
