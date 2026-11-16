export type Ci = 'green' | 'red' | 'pending' | 'none'
export type Pr = { number: number; title: string; risk?: string; ci: Ci }
export type Band = { pr?: Pr; error?: string }

declare module 'claude-code' {
  interface PluginState {
    'pr-band': { band: Band }
  }
}
