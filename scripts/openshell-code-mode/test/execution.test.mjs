import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { after, before, test } from "node:test";
import { startRuntime } from "../local-runtime.mjs";
import { benchmarkScript } from "../src/benchmark.mjs";
import { ToolError } from "../src/contracts.js";
import { createGateway } from "../src/gateway.mjs";
import { OpenShellExecutor } from "../src/openshell-executor.mjs";
import { createRegistry } from "../src/registry.js";

const token = randomBytes(32).toString("base64url");
const config = () => ({ run_id: "test-run", token, expires_at_ms: Date.now() + 30_000 });
const sourceId = "arp-synthetic-sample";
const normalized = rows => rows.map(({ tool, args, source, status }) => ({ tool, args, source, status }))
  .sort((a, b) => a.tool === b.tool && a.tool === "listSectorIssuers"
    ? a.args.sector.localeCompare(b.args.sector) : 0);

let dynamic;
before(async () => { dynamic = await startRuntime(); });
after(async () => { await dynamic.close(); });

async function sandboxRequest(gateway, tool, args, options = {}) {
  const response = await fetch(`http://127.0.0.1:${gateway.port}/tool`, {
    method: "POST",
    headers: options.headers ?? { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ run_id: options.runId ?? "test-run", tool, args }),
  });
  return { status: response.status, data: await response.json() };
}

test("the two JavaScript engines produce the original benchmark values and normalized receipts", async () => {
  const gateway = await createGateway(config());
  try {
    const registry = createRegistry();
    const fns = Object.fromEntries(Object.keys(registry.tools).map(tool => [
      tool,
      async args => {
        const response = await sandboxRequest(gateway, tool, args);
        if (response.status !== 200) throw new ToolError(response.data.error_code);
        return response.data.result;
      },
    ]));
    const baselineResponse = await dynamic.fetch("/execute", {
      method: "POST", body: JSON.stringify({ code: benchmarkScript, run_id: "baseline" }),
    });
    const baseline = await baselineResponse.json();
    assert.equal(baseline.error_code, null);
    const result = await new OpenShellExecutor().execute(benchmarkScript, [{ name: "codemode", fns }]);
    assert.deepEqual(result, { result: baseline.result });
    assert.equal(result.result.constituents, 12);
    assert.equal(result.result.total_weight_pct, 7.24);
    assert.deepEqual(result.result.top_sectors.map(row => [
      row.sector, row.weight_pct, row.largest_issuer.issuer_id,
    ]), [
      ["Information Technology", 3.10, "SYN03"],
      ["Financials", 1.40, "SYN07"],
    ]);
    const receipts = normalized(gateway.calls);
    assert.deepEqual(receipts, normalized(baseline.calls));
    assert.deepEqual(receipts.map(({tool, args}) => [tool, args]), [
      ["listBenchmarks", {}],
      ["getBenchmarkSectors", { benchmark_id: sourceId }],
      ["listSectorIssuers", { benchmark_id: sourceId, sector: "Financials" }],
      ["listSectorIssuers", { benchmark_id: sourceId, sector: "Information Technology" }],
    ]);
    assert.ok(receipts.every(row => row.status === "ok" && row.source.synthetic));
  } finally {
    await gateway.close();
  }
});

test("gateway denies missing credentials, wrong runs, and out-of-scope benchmark IDs", async () => {
  const gateway = await createGateway(config());
  try {
    for (const [tool, args, options] of [
      ["listBenchmarks", {}, { headers: {} }],
      ["listBenchmarks", {}, { runId: "different-run" }],
      ["getBenchmarkSectors", { benchmark_id: "different-snapshot" }, {}],
    ]) {
      assert.deepEqual(await sandboxRequest(gateway, tool, args, options), {
        status: 403, data: { error_code: "TOOL_DENIED" },
      });
    }
    assert.deepEqual(gateway.calls, []);
  } finally {
    await gateway.close();
  }
});

test("gateway refuses expired credentials", async () => {
  const gateway = await createGateway({ ...config(), expires_at_ms: Date.now() - 1 });
  try {
    assert.equal((await sandboxRequest(gateway, "listBenchmarks", {})).status, 403);
    assert.deepEqual(gateway.calls, []);
  } finally {
    await gateway.close();
  }
});

test("gateway rejects unregistered tools and counts every dispatched request toward the limit", async () => {
  const gateway = await createGateway(config());
  try {
    assert.deepEqual(await sandboxRequest(gateway, "unknown", {}), {
      status: 422, data: { error_code: "UNKNOWN_TOOL" },
    });
    assert.deepEqual(gateway.calls, []);
    for (let i = 0; i < 11; i += 1) {
      assert.equal((await sandboxRequest(gateway, "listBenchmarks", {})).status, 200);
    }
    assert.deepEqual(await sandboxRequest(gateway, "listBenchmarks", {}), {
      status: 422, data: { error_code: "CALL_LIMIT" },
    });
    assert.equal(gateway.calls.length, 11);
  } finally {
    await gateway.close();
  }
});

test("voting gateway exposes only voting methods and records the canonical aggregate", async () => {
  const voting = {
    snapshot_id: "synthetic-votes-v1",
    sectors: [{ sector: "Sample", eligible_votes: 2, against_votes: 1 }],
  };
  const gateway = await createGateway({ ...config(), voting });
  try {
    assert.equal((await sandboxRequest(gateway, "listBenchmarks", {})).status, 422);
    assert.deepEqual((await sandboxRequest(gateway, "aggregateVotesBySector", {
      snapshot_id: voting.snapshot_id,
    })).data.result, voting);
    assert.deepEqual(gateway.calls[0].result, voting);
  } finally {
    await gateway.close();
  }
});

test("the guest sees the JSON tool bridge with no Node globals", async () => {
  const executor = new OpenShellExecutor();
  const result = await executor.execute("async () => ({ env: typeof process, net: typeof fetch, bridge: typeof __arpCall })", {});
  assert.deepEqual(result, { result: { env: "undefined", net: "undefined", bridge: "undefined" } });
});

test("executor maps an unregistered call to a stable failure even when guest code catches it", async () => {
  const executor = new OpenShellExecutor();
  const result = await executor.execute("async () => { try { await codemode.unknown({}); } catch {} return true; }", {});
  assert.equal(result.error, "UNKNOWN_TOOL");
});

test("executor enforces deadlines, async interruption, and the result size limit", async () => {
  const executor = new OpenShellExecutor({ timeoutMs: 50 });
  assert.equal((await executor.execute("async () => { while (true) {} }", {})).error, "DEADLINE_EXCEEDED");
  assert.equal((await executor.execute("async () => await new Promise(() => {})", {})).error, "DEADLINE_EXCEEDED");
  assert.equal((await executor.execute('async () => "a".repeat(16385)', {})).error, "OUTPUT_LIMIT");
});

test("the executor stops excess tool calls before dispatching them", async () => {
  const executor = new OpenShellExecutor();
  let invoked = 0;
  const result = await executor.execute(
    "async () => { for (let i = 0; i < 13; i++) await codemode.read({}); return true; }",
    { read: async () => { invoked += 1; return true; } },
  );
  assert.equal(result.error, "CALL_LIMIT");
  assert.equal(invoked, 12);
});
