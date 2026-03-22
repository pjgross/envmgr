import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// BACKEND_PORT can be overridden for E2E tests (default: 8000 for dev)
const backendPort = process.env.BACKEND_PORT || '8000'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        target: `http://localhost:${backendPort}`,
        changeOrigin: true,
      },
    },
  },
})
