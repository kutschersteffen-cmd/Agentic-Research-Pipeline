# The sandbox service (sandbox/server.mjs) as its own container; docker-compose.yml builds it as `sandbox`.
# Debian, not alpine: the workerd binary needs glibc.
FROM node:22-bookworm-slim
# workerd refuses to start without the system CA certificates, which the slim image leaves out.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build
# Inside a container the service must listen beyond loopback; outside one the default stays 127.0.0.1.
ENV ARP_SANDBOX_HOST=0.0.0.0
USER node
EXPOSE 8790
CMD ["node", "server.mjs"]
