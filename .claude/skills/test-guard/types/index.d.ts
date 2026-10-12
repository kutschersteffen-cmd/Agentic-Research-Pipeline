export type Weakening = { file: string; before: number; after: number }

declare module 'claude-code' {
  interface PluginState {
    'test-guard': { weakenings: Weakening[] }
  }
}
