export type Run = { id: string; type: string; status: string; progress: string; cost: string }
export type Runs = { runs: Run[]; error?: string; at?: number }

declare module 'claude-code' {
  interface PluginState {
    'runs-pane': { runs: Runs }
  }
}
