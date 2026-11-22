// ARP sandbox service (spec agent-panel-code-mode, Phase 4). The backend calls it on ARP_SANDBOX_URL:
//   POST /check   {code}                              -> {ok, error}
//   POST /execute {code, token, capabilities}         -> {status: "done"|"failed"|"timeout", result, error}
//   GET  /health                                      -> {ok: true}
// Each execution gets its own workerd process, killed after the wall time, so a busy loop cannot hold the service.
import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { checkCode } from "./check.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const WORKERD = createRequire(import.meta.url)("workerd").default; // the native binary, not a node shim
const WALL_MS = Number(process.env.ARP_SANDBOX_WALL_MS ?? 30000);
const API_URL = new URL(process.env.ARP_API_URL ?? "http://127.0.0.1:8000");
const MEMORY_MB = Number(process.env.ARP_SANDBOX_MEMORY_MB ?? 512);
const BODY_LIMIT = 1 << 20;

function rssMb(pid) {  // Linux: resident set size from /proc; null where it cannot be read
  try {
    return (Number(readFileSync(`/proc/${pid}/statm`, "utf8").split(" ")[1]) * 4096) / (1 << 20);
  } catch {
    return null;
  }
}

function startWorkerd() {
  // An empty environment: nothing the service was started with reaches workerd.
  const child = spawn(
    WORKERD,
    ["serve", "sandbox.capnp", "--experimental", "--socket-addr", "http=127.0.0.1:0",
     "--external-addr", `arp=${API_URL.host}`, "--control-fd=3"],
    { cwd: here, env: {}, stdio: ["ignore", "ignore", "pipe", "pipe"] },
  );
  let stderr = "";
  child.stderr.on("data", (d) => { stderr = (stderr + d).slice(-2000); });
  const port = new Promise((resolve, reject) => {
    let buf = "";
    child.stdio[3].on("data", (d) => {
      buf += d;
      const line = buf.split("\n").find((l) => l.includes('"listen"'));
      if (line) resolve(JSON.parse(line).port);
    });
    child.on("exit", (code) => reject(new Error(`workerd exited (${code}): ${stderr.trim()}`)));
  });
  return { child, port };
}

export async function execute({ code, token, capabilities }) {
  const checked = checkCode(code);
  if (!checked.ok) return { status: "failed", result: null, error: checked.error };
  const { child, port } = startWorkerd();
  let timer, watch;
  const wall = new Promise((resolve) => {
    timer = setTimeout(() => resolve({ status: "timeout", result: null, error: `execution exceeded ${WALL_MS / 1000} s` }), WALL_MS);
  });
  // workerd has no per-isolate memory cap outside Cloudflare, so the whole process is watched and killed at the limit.
  const memory = new Promise((resolve) => {
    watch = setInterval(() => {
      if ((rssMb(child.pid) ?? 0) > MEMORY_MB) {
        child.kill("SIGKILL");
        resolve({ status: "failed", result: null, error: `execution exceeded the ${MEMORY_MB} MB memory limit` });
      }
    }, 20);
  });
  const run = (async () => {
    const res = await fetch(`http://127.0.0.1:${await port}/`, {
      method: "POST",
      body: JSON.stringify({
        code, token, capabilities: Array.isArray(capabilities) ? capabilities : [],
        api_origin: API_URL.origin, timeout_ms: WALL_MS + 5000,
      }),
    });
    const out = await res.json();
    if (out.error !== undefined) return { status: "failed", result: null, error: String(out.error) };
    if (typeof out.result_json !== "string") return { status: "failed", result: null, error: "code failed without a message" };
    return { status: "done", result: JSON.parse(out.result_json), error: null };
  })().catch((err) => ({ status: "failed", result: null, error: `sandbox error: ${err.message}` }));
  try {
    return await Promise.race([memory, run, wall]);
  } finally {
    clearTimeout(timer);
    clearInterval(watch);
    child.kill("SIGKILL");
  }
}

async function readJson(req) {
  let size = 0;
  const chunks = [];
  for await (const chunk of req) {
    size += chunk.length;
    if (size > BODY_LIMIT) throw new Error("body too large");
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function send(res, status, body) {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
}

export function createSandboxServer() {
  return createServer(async (req, res) => {
    try {
      if (req.method === "GET" && req.url === "/health") return send(res, 200, { ok: true });
      if (req.method !== "POST" || !["/check", "/execute"].includes(req.url)) return send(res, 404, { detail: "not found" });
      const body = await readJson(req);
      if (req.url === "/check") return send(res, 200, checkCode(body?.code));
      return send(res, 200, await execute(body ?? {}));
    } catch (err) {
      return send(res, 400, { detail: err.message });
    }
  });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.ARP_SANDBOX_PORT ?? 8790);
  createSandboxServer().listen(port, "127.0.0.1", () => console.log(`sandbox listening on 127.0.0.1:${port}`));
}
