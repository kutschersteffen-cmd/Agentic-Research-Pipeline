import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Cross-origin isolation: the Decision Studio rule engine runs as threaded
// WebAssembly (SharedArrayBuffer), which browsers only allow on an isolated
// page. nginx.conf sends the same two headers in production.
const isolation = {
  'Cross-Origin-Opener-Policy': 'same-origin',
  'Cross-Origin-Embedder-Policy': 'require-corp',
}

// https://vite.dev/config/
export default defineConfig({
  // VITE_API_BASE=. is the one-port build: the API serves it (ARP_FRONTEND_DIST) and every URL is
  // relative, so it also works under a path prefix such as Jupyter's /user/<id>/proxy/8000/.
  base: process.env.VITE_API_BASE === '.' ? './' : '/',
  plugins: [react()],
  // board-diagram.html is the Agent board's sandboxed diagram frame (spec agent-board, Amendment 1d).
  build: { rollupOptions: { input: { main: 'index.html', 'board-diagram': 'board-diagram.html' } } },
  server: { headers: isolation },
  preview: { headers: isolation },
})
