import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

// В dev запросы /api проксируются на живой backend (test.skypath.fun) — без CORS-возни.
// Переопределяется переменной VITE_PROXY_TARGET при необходимости.
const API_TARGET = process.env.VITE_PROXY_TARGET ?? 'https://test.skypath.fun'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@ui': fileURLToPath(new URL('../../packages/ui/src', import.meta.url)),
    },
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true, secure: true },
      '/media': { target: API_TARGET, changeOrigin: true, secure: true },
    },
  },
})
