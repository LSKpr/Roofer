import { resolve } from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

// .env lezy w katalogu glownym repo i obsluguje takze backend.
const ENV_DIR = resolve(import.meta.dirname, '..')

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ENV_DIR, '')
  return {
    plugins: [react(), tailwindcss()],
    envDir: ENV_DIR,
    // MapLibre laduje swojego workera osobnym plikiem, ktorego optymalizator Vite nie widzi.
    optimizeDeps: { exclude: ['maplibre-gl'] },
    server: {
      port: 5173,
      // Frontend wola /api na wlasnym origin, wiec CORS nie zalezy od adresu, pod ktorym
      // otwarto strone (preview, telefon w sieci lokalnej, deploy).
      proxy: { '/api': { target: env.API_PROXY_TARGET || 'http://127.0.0.1:8001', changeOrigin: false } },
    },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/setupTests.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
    },
  }
})
