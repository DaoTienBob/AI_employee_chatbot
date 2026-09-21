import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev proxy: browser calls /api/* which Vite forwards to the FastAPI backend,
// so no CORS setup is needed during development (T02).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
