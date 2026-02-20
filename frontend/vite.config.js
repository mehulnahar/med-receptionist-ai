import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const isTest = process.env.NODE_ENV === 'test' || process.argv.includes('--mode') && process.argv.includes('test')

const apiTarget = isTest
  ? 'https://backend-api-production-990c.up.railway.app'
  : 'http://localhost:8001'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        secure: true,
      },
      '/ws': {
        target: 'ws://localhost:8001',
        ws: true
      }
    }
  }
})
