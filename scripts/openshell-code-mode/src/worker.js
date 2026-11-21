import { DynamicWorkerExecutor } from "@cloudflare/codemode";
import { checkedResult, maxRequestBytes, ToolError } from "./contracts.js";
import { createRegistry } from "./registry.js";

export default {
  async fetch(request, env) {
    if (request.method !== "POST" || new URL(request.url).pathname !== "/execute") {
      return new Response(null, { status: 404 });
    }
    let payload;
    try {
      const text = await request.text();
      if (new TextEncoder().encode(text).byteLength > maxRequestBytes) throw new Error();
      payload = JSON.parse(text);
      if (typeof payload.code !== "string" || !payload.code.trim()) throw new Error();
    } catch {
      return Response.json({ result: null, error_code: "INVALID_REQUEST", calls: [] }, { status: 400 });
    }
    const registry = createRegistry({ executionId: payload.run_id });
    const executor = new DynamicWorkerExecutor({
      loader: { load: (options) => env.LOADER.load({ ...options, limits: { cpuMs: 100, subRequests: 16 } }) },
      globalOutbound: null,
      timeout: 1_500,
    });
    try {
      const binding = { callTool: (name, args) => registry.call(name, args) };
      const outcome = await executor.execute(payload.code, [], { connectors: [{ name: "codemode", binding }] });
      if (registry.errorCode) throw new ToolError(registry.errorCode);
      if (outcome.error) {
        throw new ToolError(/execution timed out|timed out after|time limit|exceeded.*timeout/i.test(outcome.error)
          ? "DEADLINE_EXCEEDED" : "INVALID_RESULT");
      }
      return Response.json({ result: checkedResult(outcome.result), error_code: null, calls: registry.calls });
    } catch (error) {
      return Response.json({
        result: null,
        error_code: error instanceof ToolError ? error.code : "INVALID_RESULT",
        calls: registry.calls,
      }, { status: 422 });
    }
  },
};
