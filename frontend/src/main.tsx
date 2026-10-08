import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// A tab left open across a deploy still points at old hashed page chunks, which
// 404 and would blank the app. Reload to pick up the new build (at most once per 10s, so a truly missing chunk cannot loop).
window.addEventListener('vite:preloadError', (e) => {
  try {
    const last = Number(sessionStorage.getItem('chunk-reload'))
    if (Date.now() - last < 10_000) return
    sessionStorage.setItem('chunk-reload', String(Date.now()))
  } catch {
    return
  }
  e.preventDefault()
  location.reload()
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
