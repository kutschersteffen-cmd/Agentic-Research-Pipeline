// Host worker: runs one exploration's code in a fresh workerd isolate (spec agent-panel-code-mode, Phase 4).
// The isolate sees one object, `codemode`; each method call comes back here over RPC. A capability outside the
// execution's list is refused without calling ARP; the rest go to ARP's tool route with the execution token, which
// stays in this worker and never enters the isolate.
import { DynamicWorkerExecutor, normalizeCode } from "@cloudflare/codemode";
import { RpcTarget } from "cloudflare:workers";

const RESULT_LIMIT = 262144;

class Capabilities extends RpcTarget {
  constructor(job, env) {
    super();
    this.job = job;
    this.env = env;
    this.breach = null; // the first limit or lane breach: it fails the execution even if the code catches it
  }

  async callTool(name, args) {
    if (!this.job.capabilities.includes(name)) {
      const message = `${name} is not available in the sandbox`;
      this.breach ??= message;
      return { __codemode_control__: "error", message };
    }
    const res = await this.env.ARP.fetch(`${this.job.api_origin}/api/sandbox/tools/${encodeURIComponent(name)}`, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${this.job.token}` },
      body: JSON.stringify(args ?? {}),
    });
    const body = await res.json().catch(() => null);
    if (res.ok) return body;
    const message = typeof body?.detail === "string" ? body.detail : `${name} failed with HTTP ${res.status}`;
    if (res.status === 429) this.breach ??= message;
    return { __codemode_control__: "error", message };
  }
}

// The executor reports a throw as `err.message`, which is undefined for a thrown string, object or empty Error, and
// would then read as a result. Rethrow every throw as an Error with a non-empty message.
function wrapThrows(code) {
  return `async () => {
  try {
    return await (${normalizeCode(code)})();
  } catch (e) {
    if (e instanceof Error) throw new Error(e.message || e.name || "Error");
    let text;
    try { text = typeof e === "string" ? e : JSON.stringify(e); } catch { text = undefined; }
    throw new Error("code threw " + (text ?? String(e)));
  }
}`;
}

export default {
  async fetch(request, env) {
    const job = await request.json();
    // No nodejs_compat in the isolate: no `process`, no Node modules. Its outbound fetch and connect go to DENY.
    const loader = { load: (config) => env.LOADER.load({ ...config, compatibilityFlags: [] }) };
    const executor = new DynamicWorkerExecutor({ loader, globalOutbound: env.DENY, timeout: job.timeout_ms });
    const caps = new Capabilities(job, env);
    let out;
    try {
      out = await executor.execute(wrapThrows(job.code), [], { connectors: [{ name: "codemode", binding: caps }] });
    } catch (err) {
      out = { error: err instanceof Error ? err.message : String(err) };
    }
    if (caps.breach) return Response.json({ error: caps.breach });
    if (out.error !== undefined) return Response.json({ error: out.error });
    let json;
    try {
      json = JSON.stringify(out.result ?? null);
      if (json === undefined) throw new Error(`a ${typeof out.result} has no JSON form`);
    } catch (err) {
      return Response.json({ error: `result is not JSON: ${err.message}` });
    }
    if (new TextEncoder().encode(json).length > RESULT_LIMIT) return Response.json({ error: "result exceeds 256 KB" });
    return Response.json({ result_json: json });
  },
};
