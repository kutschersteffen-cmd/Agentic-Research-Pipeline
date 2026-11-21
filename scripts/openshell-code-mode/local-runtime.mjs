import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { Miniflare, convertV4MiniflareOptions } from "miniflare";

export async function startRuntime() {
  const { outputFiles } = await build({
    entryPoints: [fileURLToPath(new URL("./src/worker.js", import.meta.url))],
    bundle: true,
    format: "esm",
    platform: "neutral",
    external: ["cloudflare:*"],
    write: false,
  });
  const runtime = new Miniflare(convertV4MiniflareOptions({
    host: "127.0.0.1",
    cf: false,
    modules: true,
    script: outputFiles[0].text,
    compatibilityDate: "2026-07-01",
    workerLoaders: { LOADER: {} },
  }));
  return {
    fetch: (path, options) => runtime.dispatchFetch("http://localhost" + path, options),
    close: () => runtime.dispose(),
  };
}

export function runScript(runtime, code) {
  return runtime.fetch("/execute", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
}
