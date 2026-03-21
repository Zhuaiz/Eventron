import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        // In Docker: app:8000; local dev: localhost:8000
        target: process.env.VITE_API_BASE || 'http://localhost:8000',
        changeOrigin: true,
      },
      '/p': {
        // Public check-in routes (no auth)
        target: process.env.VITE_API_BASE || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
