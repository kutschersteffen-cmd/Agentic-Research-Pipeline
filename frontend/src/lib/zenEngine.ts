import { getDefaultContext, instantiateNapiModule, WASI } from "@napi-rs/wasm-runtime";
import wasmUrl from "@gorules/zen-engine-wasm32-wasi/zen-engine.wasm32-wasi.wasm?url";
import type { RuleGraph } from "../types";

// The GoRules ZEN engine compiled to WebAssembly: the same 2.0.2 build the
// backend scores with (backend/pyproject.toml pins it in lockstep), so a
// rule previewed here evaluates exactly as it will be scored. This mirrors
// the package's own zen-engine.wasi-browser.js, with the worker and wasm
// URLs written so Vite can bundle them.
//
// It needs SharedArrayBuffer, which browsers only grant to a
// cross-origin-isolated page: vite.config.ts and nginx.conf send the
// COOP/COEP headers that make it one.

export interface ZenTrace {
  id: string;
  name: string;
  input: unknown;
  output: unknown;
  performance: string | null;
  traceData: unknown;
  order?: number;
}

export interface ZenResponse {
  performance: string;
  result: Record<string, unknown>;
  trace?: Record<string, ZenTrace>;
}

interface ZenDecision {
  evaluate(context: unknown, opts?: { trace?: boolean }): Promise<ZenResponse>;
}

interface ZenEngine {
  createDecision(content: object): ZenDecision;
}

let engine: Promise<ZenEngine> | null = null;

/** Loads the 14 MB engine once, on first use. */
export function loadZen(): Promise<ZenEngine> {
  engine ??= instantiate().catch((error) => {
    engine = null;
    throw error;
  });
  return engine;
}

async function instantiate(): Promise<ZenEngine> {
  if (!globalThis.crossOriginIsolated) {
    throw new Error("the page is not cross-origin isolated (COOP/COEP headers missing), so the browser engine cannot start");
  }
  const memory = new WebAssembly.Memory({ initial: 1024, maximum: 16384, shared: true });
  const bytes = await fetch(wasmUrl).then((response) => response.arrayBuffer());
  const { napiModule } = await instantiateNapiModule(bytes, {
    context: getDefaultContext(),
    asyncWorkPoolSize: 4,
    wasi: new WASI({ version: "preview1" }),
    onCreateWorker: () => new Worker(new URL("./zenWorker.ts", import.meta.url), { type: "module" }),
    overwriteImports(importObject) {
      importObject.env = { ...importObject.env, ...importObject.napi, ...importObject.emnapi, memory };
      return importObject;
    },
    beforeInit({ instance }) {
      for (const name of Object.keys(instance.exports)) {
        if (name.startsWith("__napi_register__")) (instance.exports[name] as () => void)();
      }
    },
  });
  const { ZenEngine } = napiModule.exports as { ZenEngine: new () => ZenEngine };
  return new ZenEngine();
}

/** The engine reports a failed node as a JSON string; keep the readable part. */
export function zenErrorText(error: unknown): string {
  const text = error instanceof Error ? error.message : String(error);
  try {
    const parsed = JSON.parse(text.split("\n")[0]);
    return String(parsed.source ?? parsed.message ?? text);
  } catch {
    return text;
  }
}

export async function evaluateGraph(graph: RuleGraph, context: Record<string, unknown>, trace = false): Promise<ZenResponse> {
  const zen = await loadZen();
  return zen.createDecision(graph).evaluate(context, { trace });
}
