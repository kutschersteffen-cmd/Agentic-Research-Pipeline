import { getQuickJS } from "quickjs-emscripten";
import { normalizeCode } from "./codemode-portable.js";
import { checkedResult, maxCalls, maxRequestBytes, maxResultBytes, ToolError, toolErrorCodes } from "./contracts.js";

function getFunctions(providers) {
  if (providers.length !== 1 || providers[0].name !== "codemode" || providers[0].prelude) {
    throw new ToolError("INVALID_REQUEST");
  }
  return providers[0].fns;
}

function pump(context) {
  const result = context.runtime.executePendingJobs();
  if (result.error) {
    result.error.dispose();
    throw new ToolError("INVALID_RESULT");
  }
}

function failureCode(error) {
  return error instanceof ToolError && toolErrorCodes.has(error.code) ? error.code : "INVALID_RESULT";
}

// Implements the pinned Code Mode Executor contract inside the OpenShell image.
// QuickJS exposes only the JSON tool bridge, while OpenShell supplies process and network isolation.
export class OpenShellExecutor {
  constructor({ timeoutMs = 29_000 } = {}) {
    this.timeoutMs = timeoutMs;
  }

  /** @type {import("@cloudflare/codemode").Executor["execute"]} */
  async execute(code, providersOrFns, options) {
    let context;
    let promise;
    let timer;
    let timedOut = false;
    let fatalError = null;
    let stopped = false;
    const pending = new Set();
    const controller = new AbortController();
    try {
      if (options?.connectors?.length) throw new ToolError("INVALID_REQUEST");
      const fns = getFunctions(Array.isArray(providersOrFns)
        ? providersOrFns : [{ name: "codemode", fns: providersOrFns }]);
      const normalized = normalizeCode(code);
      const engine = await getQuickJS();
      context = engine.newContext();
      const deadline = performance.now() + this.timeoutMs;
      context.runtime.setMemoryLimit(24 * 1024 * 1024);
      context.runtime.setMaxStackSize(256 * 1024);
      context.runtime.setInterruptHandler(() => (timedOut = performance.now() >= deadline));

      let rejectPump;
      const pumpFailure = new Promise((_, reject) => { rejectPump = reject; });
      let requests = 0;
      const bridge = context.newFunction("arpCall", (tool, body) => {
        requests += 1;
        if (requests > maxCalls) {
          fatalError ??= "CALL_LIMIT";
          throw new ToolError("CALL_LIMIT");
        }
        const method = context.getString(tool);
        const input = context.getString(body);
        const deferred = context.newPromise();
        pending.add(deferred);
        // Schedule outside the VM callback so that resolving a result never re-enters the VM.
        Promise.resolve().then(async () => {
          try {
            if (!Object.hasOwn(fns, method)) throw new ToolError("UNKNOWN_TOOL");
            if (Buffer.byteLength(input) > maxRequestBytes) throw new ToolError("INVALID_ARGUMENTS");
            const output = await fns[method](JSON.parse(input), controller.signal);
            if (stopped) return;
            const value = context.newString(JSON.stringify(checkedResult(output)));
            try {
              deferred.resolve(value);
            } finally {
              value.dispose();
            }
          } catch (error) {
            if (stopped) return;
            fatalError ??= failureCode(error);
            const value = context.newString(fatalError);
            try {
              deferred.reject(value);
            } finally {
              value.dispose();
            }
          }
          if (!stopped) {
            pending.delete(deferred);
            pump(context);
          }
        }).catch(rejectPump);
        return deferred.handle;
      });
      try {
        context.setProp(context.global, "__arpCall", bridge);
      } finally {
        bridge.dispose();
      }

      // Capture the bridge before loading the script. Guest code receives no Node objects.
      const setup = context.unwrapResult(context.evalCode(`
        globalThis.codemode = (() => {
          const dispatch = globalThis.__arpCall;
          delete globalThis.__arpCall;
          return new Proxy(Object.create(null), {
            get: (_, name) => typeof name === "string"
              ? async (args) => JSON.parse(await dispatch(name, JSON.stringify(args)))
              : undefined,
          });
        })();
      `, "bindings.js"));
      setup.dispose();
      promise = context.unwrapResult(context.evalCode(`
        (async () => {
          const stringify = JSON.stringify;
          return stringify(await (${normalized})());
        })();
      `, "job.js"));
      const settled = context.resolvePromise(promise);
      const timeout = new Promise((_, reject) => {
        timer = setTimeout(() => {
          timedOut = true;
          reject(new ToolError("DEADLINE_EXCEEDED"));
        }, Math.max(1, deadline - performance.now()));
      });
      pump(context);
      const result = context.unwrapResult(await Promise.race([settled, timeout, pumpFailure]));
      try {
        if (fatalError) throw new ToolError(fatalError);
        if (context.typeof(result) !== "string") throw new ToolError("INVALID_RESULT");
        const serialized = context.getString(result);
        if (Buffer.byteLength(serialized) > maxResultBytes) throw new ToolError("OUTPUT_LIMIT");
        return { result: JSON.parse(serialized) };
      } finally {
        result.dispose();
      }
    } catch (error) {
      const code = timedOut ? "DEADLINE_EXCEEDED"
        : fatalError ?? (error instanceof ToolError ? error.code : "INVALID_RESULT");
      return { result: undefined, error: code };
    } finally {
      stopped = true;
      clearTimeout(timer);
      controller.abort();
      promise?.dispose();
      for (const deferred of pending) deferred.dispose();
      context?.dispose();
    }
  }
}
