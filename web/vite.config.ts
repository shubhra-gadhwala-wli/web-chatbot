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
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
})
