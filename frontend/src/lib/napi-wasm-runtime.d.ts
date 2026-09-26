// @napi-rs/wasm-runtime ships no type declarations; this covers the calls
// zenEngine.ts and zenWorker.ts make.
declare module "@napi-rs/wasm-runtime" {
  type Imports = Record<string, Record<string, unknown>>;
  interface InstantiateOptions {
    context?: unknown;
    asyncWorkPoolSize?: number;
    childThread?: boolean;
    wasi: WASI;
    onCreateWorker?: () => Worker;
    overwriteImports?: (importObject: Imports) => Imports;
    beforeInit?: (source: { instance: WebAssembly.Instance }) => void;
  }
  interface Instantiated {
    napiModule: { exports: Record<string, unknown> };
  }
  export class WASI {
    constructor(options?: Record<string, unknown>);
  }
  export class MessageHandler {
    constructor(options: { onLoad: (data: { wasmModule: WebAssembly.Module; wasmMemory: WebAssembly.Memory }) => Instantiated });
    handle(event: MessageEvent): void;
  }
  export function getDefaultContext(): unknown;
  export function instantiateNapiModule(bytes: ArrayBuffer, options: InstantiateOptions): Promise<Instantiated>;
  export function instantiateNapiModuleSync(module: WebAssembly.Module, options: InstantiateOptions): Instantiated;
}
