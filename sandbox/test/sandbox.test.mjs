// node --test: the sandbox against a stand-in ARP tool route.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import { createServer } from "node:http";
import { syncBuiltinESMExports } from "node:module";
import { after, before, test } from "node:test";

let api;
const seen = [];
let execute;
let checkCode;

before(async () => {
  api = createServer((req, res) => {
    let body = "";
    req.on("data", (d) => { body += d; });
    req.on("end", () => {
      seen.push({ url: req.url, auth: req.headers.authorization, body: JSON.parse(body) });
      const limited = seen.length > 3;
      res.writeHead(limited ? 429 : 200, { "content-type": "application/json" });
      res.end(JSON.stringify(limited ? { detail: "capability call limit 3 exceeded" } : { echo: JSON.parse(body) }));
    });
  });
  await new Promise((r) => api.listen(0, "127.0.0.1", r));
  process.env.ARP_API_URL = `http://127.0.0.1:${api.address().port}`;
  process.env.ARP_SANDBOX_WALL_MS = "5000";
  process.env.ARP_SANDBOX_MEMORY_MB = "256";
  ({ execute } = await import("../server.mjs"));
  ({ checkCode } = await import("../check.mjs"));
});

after(() => api.close());

const run = (code, capabilities = ["benchmark_sectors"]) => execute({ code, token: "tok", capabilities });

test("runs code and returns its result", async () => {
  assert.deepEqual(await run("return 1 + 1"), { status: "done", result: 2, error: null });
});

test("a capability call reaches the tool route with the token, which the code cannot see", async () => {
  seen.length = 0;
  const out = await run('const r = await codemode.benchmark_sectors({benchmark_id: null}); return [r, typeof token]');
  assert.equal(out.status, "done");
  assert.deepEqual(out.result, [{ echo: { benchmark_id: null } }, "undefined"]);
  assert.deepEqual(seen, [{ url: "/api/sandbox/tools/benchmark_sectors", auth: "Bearer tok", body: { benchmark_id: null } }]);
});

test("no network", async () => {
  const out = await run('return await fetch("https://example.com")');
  assert.equal(out.status, "failed");
  assert.match(out.error, /network access is not allowed/);
});

test("no process, no token global", async () => {
  assert.equal((await run('return typeof process + "," + typeof globalThis.ARP_TOKEN')).result, "undefined,undefined");
});

test("a capability outside the list fails without calling ARP, even when the code catches it", async () => {
  seen.length = 0;
  const out = await run("try { await codemode.universe_build({}) } catch (e) {} return 1");
  assert.deepEqual(out, { status: "failed", result: null, error: "universe_build is not available in the sandbox" });
  assert.equal(seen.length, 0);
});

test("the tool route's call limit fails the execution, even when the code catches it", async () => {
  seen.length = 0;
  const out = await run("for (let i = 0; i < 5; i++) { try { await codemode.benchmark_sectors({}) } catch (e) {} } return 1");
  assert.equal(out.status, "failed");
  assert.equal(out.error, "capability call limit 3 exceeded");
});

test("a busy loop times out and the service still runs the next execution", async () => {
  assert.equal((await run("while (true) {}")).status, "timeout");
  assert.equal((await run("return 3")).result, 3);
});

test("result over 256 KB fails", async () => {
  const out = await run('return "a".repeat(300000)');
  assert.deepEqual(out, { status: "failed", result: null, error: "result exceeds 256 KB" });
});

test("code checks: 400 lines pass, 401 fail before running; a parse error names it", async () => {
  assert.deepEqual(checkCode(Array(400).fill("1;").join("\n")), { ok: true, error: null });
  assert.deepEqual(await run(Array(401).fill("1;").join("\n")), { status: "failed", result: null, error: "code exceeds 400 lines" });
  const parsed = checkCode("return (");
  assert.equal(parsed.ok, false);
  assert.match(parsed.error, /^code does not parse: /);
});

test("code that throws a value that is not an Error fails", async () => {
  assert.deepEqual(await run('throw "no data"'), { status: "failed", result: null, error: "code threw no data" });
  assert.deepEqual(await run("await Promise.reject({code: 1})"), { status: "failed", result: null, error: 'code threw {"code":1}' });
  assert.deepEqual(await run("throw new Error()"), { status: "failed", result: null, error: "Error" });
  assert.deepEqual(await run('throw new Error("x")'), { status: "failed", result: null, error: "x" });
});

test("an execution over the memory limit is killed and fails", async () => {
  const t0 = Date.now();
  const out = await run("const a = []; let i = 0; while (true) { a.push(new Uint8Array(1e6).fill(i++ % 255)); }");
  assert.deepEqual(out, { status: "failed", result: null, error: "execution exceeded the 256 MB memory limit" });
  assert.ok(Date.now() - t0 < 4000);
  assert.equal((await run("return 4")).result, 4);
});

test("a throw whose message or string form itself throws still fails", async () => {
  const getter = 'const e = new Error(); Object.defineProperty(e, "message", {get() { throw "boom" }}); throw e';
  assert.deepEqual(await run(getter), { status: "failed", result: null, error: "code threw a value" });
  assert.deepEqual(await run("throw {toJSON() { throw 1 }, toString() { throw 2 }}"),
    { status: "failed", result: null, error: "code threw a value" });
});

test("memory is read as kB from the VmRSS line of the process status", async () => {
  const read = fs.readFileSync;
  fs.readFileSync = (path, ...rest) => /^\/proc\/\d+\/status$/.test(path) ? "Name:\tworkerd\nVmRSS:\t300000 kB\n" : read(path, ...rest);
  syncBuiltinESMExports();
  try {
    assert.deepEqual(await run("while (true) {}"),
      { status: "failed", result: null, error: "execution exceeded the 256 MB memory limit" });
  } finally {
    fs.readFileSync = read;
    syncBuiltinESMExports();
  }
});

test("without a VmRSS line the service starts and says the memory limit is off", async () => {
  // Preloaded into the service: its own process status has no VmRSS line, as on a system without /proc.
  const noRss = `import fs from "node:fs"; import { syncBuiltinESMExports } from "node:module"; const read = fs.readFileSync;
    fs.readFileSync = (p, ...r) => p === "/proc/self/status" ? "Name:\\tnode\\n" : read(p, ...r); syncBuiltinESMExports();`;
  const child = spawn(process.execPath, ["--import", `data:text/javascript,${encodeURIComponent(noRss)}`, "server.mjs"],
    { cwd: new URL("..", import.meta.url), env: { ...process.env, ARP_SANDBOX_PORT: "0" } });
  let out = "", err = "";
  child.stderr.on("data", (d) => { err += d; });
  await new Promise((resolve) => child.stdout.on("data", (d) => { out += d; if (out.includes("listening")) resolve(); }));
  child.kill();
  assert.match(out, /^sandbox listening on 127\.0\.0\.1:0/);
  assert.match(err, /memory limit off: cannot read process memory on this system, so ARP_SANDBOX_MEMORY_MB is not enforced/);
});
