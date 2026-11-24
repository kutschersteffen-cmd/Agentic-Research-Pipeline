# syntax=docker/dockerfile:1
#
# Corporate Readiness Plan, Phase 1 (see docs/CORPORATE_READINESS_PLAN.md).
# Builds the Vite/React frontend into a static bundle served by nginx.
# `npm run dev` (see README "Setup") keeps working exactly as before --
# this is an additional, opt-in path.
#
# VITE_API_BASE defaults to empty: the built page calls the API on its own
# origin (/api/...), and nginx in this image forwards /api/ to ARP_BACKEND_URL
# (default http://backend:8000; scheme, host and port only, no path or trailing
# slash). `npm run dev` leaves VITE_API_BASE unset and still calls http://localhost:8000.
# nginx proxies /api/ only for the host names in ARP_PUBLIC_HOSTS (space-separated,
# default "localhost 127.0.0.1"); any other Host gets 421. Add the name you reach
# ARP under, e.g. ARP_PUBLIC_HOSTS="localhost 127.0.0.1 arp.internal".
#   docker build -t arp-frontend frontend/
#   docker run -e ARP_BACKEND_URL=http://my-backend:8000 -p 127.0.0.1:5173:80 arp-frontend
#
# Keep the published port bound to 127.0.0.1 while the backend runs in dev
# sign-in mode (README "Sign-in"): every /api/ request through this container
# reaches the backend from a trusted address, so publishing it on 0.0.0.0 makes
# every host on the network the dev approver. Put TLS and real sign-in in front first.

FROM node:22-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json .npmrc ./
RUN npm ci

COPY . .

ARG VITE_API_BASE=""
ENV VITE_API_BASE=${VITE_API_BASE}
RUN npm run build

FROM nginx:1.27-alpine AS runtime

COPY --from=builder /app/dist /usr/share/nginx/html
# A template: nginx's entrypoint fills in the names below at container start
# and writes /etc/nginx/conf.d/default.conf (see nginx.conf).
COPY nginx.conf /etc/nginx/templates/default.conf.template
ENV ARP_BACKEND_URL=http://backend:8000 \
    ARP_PUBLIC_HOSTS="localhost 127.0.0.1" \
    NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 \
    NGINX_ENVSUBST_FILTER="^(ARP_BACKEND_URL|ARP_PUBLIC_HOSTS|NGINX_LOCAL_RESOLVERS)$"

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q --spider http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
