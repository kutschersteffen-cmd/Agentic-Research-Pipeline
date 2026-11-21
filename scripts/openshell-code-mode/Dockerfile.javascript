FROM node:24.22.2-bookworm-slim
ENV NODE_USE_ENV_PROXY=1
WORKDIR /opt/arp-code-mode
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund
COPY sandbox.mjs sandbox-probe.mjs ./
COPY src/contracts.js src/codemode-portable.js src/openshell-executor.mjs ./src/
RUN install -d -o 1000 -g 1000 /workspace
WORKDIR /workspace
