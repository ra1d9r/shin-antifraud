import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Порт 5173 уже разрешён в CORS backend (см. CORS_ORIGINS в .env).
//
// `host` задан явно: по умолчанию Vite поднимался только на IPv6 (`::1`),
// и адрес http://127.0.0.1:5173 отказывал в соединении — при том, что
// именно он чаще всего написан в инструкциях и вбит в закладки.
// 127.0.0.1 оставляет сервер на петле: в отличие от `host: true`,
// он не выставляет dev-сервер в локальную сеть.
export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
})
