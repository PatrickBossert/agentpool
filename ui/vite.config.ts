import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  base: '/dashboard',
  plugins: [react()],
  server: {
    // One entry per top-level prefix the API mounts. api/client.ts sends origin-relative
    // URLs, so in development that origin is this dev server and anything missing from this
    // list is answered by Vite's SPA fallback instead of the API. It stayed invisible for as
    // long as it did only because the old absolute base bypassed the proxy altogether.
    // tests/test_proxy_prefix_coverage.py enumerates app.routes and fails when a prefix is
    // missing from here or from the Caddyfile.
    proxy: {
      '/projects': 'http://localhost:8000',
      '/auth': 'http://localhost:8000',
      '/admin': 'http://localhost:8000',
      '/system': 'http://localhost:8000',
      '/agent-skill-notes': 'http://localhost:8000',
      // The two routers that carry an /api prefix of their own - templates and interviews.
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
