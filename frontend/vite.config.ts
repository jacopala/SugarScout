import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// In development the SPA calls /api/*, proxied to the FastAPI service on :8000.
// In deployed environments VITE_API_BASE_URL points at the Render API service.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    // Demo over an HTTPS tunnel (`cloudflared tunnel --url ...`) so phones get push and
    // the mic. `vite preview` inherits this and the /api proxy below.
    allowedHosts: ['.trycloudflare.com'],
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_API_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
})
