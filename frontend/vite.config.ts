import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Порт 5173 уже разрешён в CORS backend (см. CORS_ORIGINS в .env).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
})
