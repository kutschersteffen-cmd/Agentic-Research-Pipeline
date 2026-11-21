import { open } from "node:fs/promises";
import { OpenShellExecutor } from "./src/openshell-executor.mjs";
import { checkedResult, maxRequestBytes, ToolError, toolErrorCodes } from "./src/contracts.js";

async function readJob(path) {
  const file = await open(path, "r");
  try {
    const buffer = Buffer.alloc(maxRequestBytes + 1);
    let total = 0;
    for (;;) {
      const { bytesRead } = await file.read(buffer, total, buffer.length - total, null);
      if (bytesRead === 0) break;
      total += bytesRead;
      if (total === buffer.length) throw new ToolError("INVALID_REQUEST");
    }
    return JSON.parse(buffer.toString("utf8", 0, total));
  } finally {
    await file.close();
  }
}

function validate(job) {
  const gateway = new URL(job.gateway_url);
  if (gateway.protocol !== "https:" || gateway.pathname !== "/tool" || gateway.search
      || gateway.hash || gateway.username || gateway.password || typeof job.code !== "string"
      || !job.code.trim() || typeof job.run_id !== "string" || !job.run_id
      || typeof job.token !== "string" || !/^[A-Za-z0-9_-]{32,128}$/.test(job.token)
      || !Array.isArray(job.tools) || job.tools.length < 1 || job.tools.length > 12
      || job.tools.some(name => typeof name !== "string" || !/^[A-Za-z_][A-Za-z0-9_]{0,79}$/.test(name))) {
    throw new ToolError("INVALID_REQUEST");
  }
  return gateway;
}

async function run(job) {
  const gateway = validate(job);
  const fns = Object.fromEntries(job.tools.map(tool => [
    tool, async (args, signal) => {
      const response = await fetch(gateway, {
        method: "POST",
        redirect: "error",
        headers: { "content-type": "application/json", authorization: `Bearer ${job.token}` },
        body: JSON.stringify({ run_id: job.run_id, tool, args }),
        signal,
      });
      const value = await response.json();
      if (!response.ok) {
        throw new ToolError(toolErrorCodes.has(value.error_code) ? value.error_code : "TOOL_DENIED");
      }
      return checkedResult(value.result);
    },
  ]));
  const outcome = await new OpenShellExecutor().execute(job.code, [{ name: "codemode", fns }]);
  return { result: outcome.result ?? null, error_code: outcome.error ?? null };
}

async function main() {
  let value;
  try {
    value = await run(await readJob(process.argv[2]));
  } catch (error) {
    value = { result: null, error_code: error instanceof ToolError ? error.code : "INVALID_REQUEST" };
  }
  process.stdout.write(JSON.stringify(value) + "\n");
}

await main();
