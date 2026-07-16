import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// В dev /api проксируется на локальный backend. В prod админка отдаётся с того же
// домена, что и API (VITE_API_BASE пуст → относительный путь).
const API_TARGET = process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5174,
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
      '/media': { target: API_TARGET, changeOrigin: true },
    },
  },
})
