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
  plugins: [react()],
  server: { headers: isolation },
  preview: { headers: isolation },
})
