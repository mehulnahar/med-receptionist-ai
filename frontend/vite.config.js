import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const isTest = process.env.NODE_ENV === 'test' || process.argv.includes('--mode') && process.argv.includes('test')

// Never hardcode production URLs — use VITE_TEST_API_URL env var for test targets
// to prevent accidentally sending test data to production.
const apiTarget = isTest
  ? (process.env.VITE_TEST_API_URL || 'http://localhost:8000')
  : (process.env.VITE_DEV_API_TARGET || 'http://localhost:8000')

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        secure: isTest,
      },
      '/ws': {
        target: process.env.VITE_DEV_WS_TARGET || 'ws://localhost:8000',
        ws: true
      }
    }
  }
})
