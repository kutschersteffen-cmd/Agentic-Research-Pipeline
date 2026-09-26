// Thread worker for the ZEN engine's async evaluations -- the package's
// wasi-worker-browser.mjs, kept beside zenEngine.ts so Vite bundles it.
import { instantiateNapiModuleSync, MessageHandler, WASI } from "@napi-rs/wasm-runtime";

const handler = new MessageHandler({
  onLoad({ wasmModule, wasmMemory }) {
    return instantiateNapiModuleSync(wasmModule, {
      childThread: true,
      wasi: new WASI({ print: console.log, printErr: console.error }),
      overwriteImports(importObject) {
        importObject.env = { ...importObject.env, ...importObject.napi, ...importObject.emnapi, memory: wasmMemory };
        return importObject;
      },
    });
  },
});

globalThis.onmessage = (event: MessageEvent) => handler.handle(event);
