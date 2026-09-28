import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
// Dev-only proxy so the browser sees same-origin /api/v1 requests (R6);
// production serves the built UI and API from the same FastAPI origin
// per the architecture's local topology.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api/v1': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: false,
        // The backend enforces same-origin via the Origin/Referer header (R6).
        // Vite's dev server runs on a different port than the backend, so the
        // browser's real Origin (this dev server) must be rewritten to the
        // backend's own origin for the proxy to look same-origin to it.
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            proxyReq.setHeader('origin', 'http://127.0.0.1:8080')
          })
        },
      },
    },
  },
})
