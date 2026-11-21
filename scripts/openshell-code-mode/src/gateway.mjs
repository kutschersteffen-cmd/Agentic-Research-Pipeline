import { timingSafeEqual } from "node:crypto";
import { createServer } from "node:http";
import { once } from "node:events";
import { isIP } from "node:net";
import { createRegistry } from "./registry.js";
import { maxRequestBytes, ToolError } from "./contracts.js";

function json(response, status, data) {
  response.writeHead(status, { "content-type": "application/json", "cache-control": "no-store" });
  response.end(JSON.stringify(data));
}

async function readBody(request) {
  let bytes = 0;
  const chunks = [];
  for await (const chunk of request) {
    bytes += chunk.length;
    if (bytes > maxRequestBytes) {
      throw new ToolError("INVALID_REQUEST");
    }
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function hasToken(request, token) {
  const actual = Buffer.from(request.headers.authorization ?? "");
  return actual.length === token.length && timingSafeEqual(actual, token);
}

export async function createGateway({
  run_id: runId, token, expires_at_ms: expiresAt, listen_host: host = "127.0.0.1",
  listen_port: port = 0, voting,
}) {
  if (typeof token !== "string" || !/^[A-Za-z0-9_-]{32,128}$/.test(token)
      || typeof runId !== "string" || !runId || !Number.isSafeInteger(expiresAt)
      || !isIP(host) || !Number.isInteger(port) || port < 0 || port > 65535) {
    throw new ToolError("INVALID_REQUEST");
  }
  const bearer = Buffer.from(`Bearer ${token}`);
  const registry = createRegistry({ executionId: runId, voting });
  const server = createServer(async (request, response) => {
    if (request.method !== "POST" || request.url !== "/tool") {
      request.resume();
      return json(response, 404, { error_code: "UNKNOWN_ENDPOINT" });
    }
    if (Date.now() >= expiresAt || !hasToken(request, bearer)) {
      request.resume();
      return json(response, 403, { error_code: "TOOL_DENIED" });
    }
    try {
      const payload = await readBody(request);
      if (payload?.run_id !== runId || Date.now() >= expiresAt) {
        return json(response, 403, { error_code: "TOOL_DENIED" });
      }
      if (typeof payload.tool !== "string") throw new ToolError("INVALID_REQUEST");
      const result = await registry.call(payload.tool, payload.args);
      return json(response, 200, { result });
    } catch (error) {
      const code = error instanceof ToolError ? error.code : "INVALID_REQUEST";
      return json(response, code === "TOOL_DENIED" ? 403 : 422, { error_code: code });
    }
  });
  server.requestTimeout = 30_000;
  server.listen({ host, port });
  await once(server, "listening");
  return {
    port: server.address().port,
    calls: registry.calls,
    get errorCode() { return registry.errorCode; },
    close: () => new Promise((resolve, reject) => {
      server.close(error => error ? reject(error) : resolve());
      server.closeAllConnections();
    }),
  };
}
