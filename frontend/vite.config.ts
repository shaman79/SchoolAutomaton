import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// Dev proxies /api and /openapi.json to the FastAPI backend so the SPA is same-origin in dev.
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  // Don't emit the inline modulepreload-polyfill <script> — it trips our strict CSP
  // (script-src 'self'), and modern browsers support modulepreload natively.
  build: {
    modulePreload: { polyfill: false },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/openapi.json': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
