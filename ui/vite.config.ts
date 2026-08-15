import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: '/dashboard',
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      // The agent log stream. useWebSocket derives its URL from the page origin, so in dev
      // that origin is this server and the socket has to be forwarded on - ws: true is what
      // makes the proxy upgrade the connection rather than answer it as a plain request.
      '/ws': { target: 'http://localhost:8000', ws: true },
    },
  },
  test: {
    environment: 'jsdom',
    environmentOptions: {
      jsdom: {
        url: 'http://localhost',
      },
    },
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
  },
})
