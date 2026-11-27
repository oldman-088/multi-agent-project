import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

/**
 * Vite configuration for the NEXUS AGENT OS web app.
 *
 * - `server.host` is `0.0.0.0` so the dev server works inside a container and
 *   under the preview proxy (never bind to 127.0.0.1).
 * - `server.allowedHosts` accepts the proxied preview host as well as localhost.
 * - `/api` and `/ws` are proxied to the backend so the frontend only ever uses
 *   relative URLs (AGENTS.md frontend rule: never `localhost` in frontend code).
 */
const BACKEND_URL = process.env.NEXUS_BACKEND_URL ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: false,
    allowedHosts: ['.e2b.app', 'localhost', '127.0.0.1'],
    proxy: {
      '/api': { target: BACKEND_URL, changeOrigin: true },
      '/ws': { target: BACKEND_URL, ws: true, changeOrigin: true },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 4173,
    allowedHosts: ['.e2b.app', 'localhost', '127.0.0.1'],
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    target: 'es2022',
  },
});
