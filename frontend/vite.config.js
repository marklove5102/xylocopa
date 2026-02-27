import fs from 'node:fs'
import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Load self-signed certs for HTTPS (needed for microphone access over LAN)
const certsDir = path.resolve(__dirname, '../certs')
const httpsConfig = fs.existsSync(path.join(certsDir, 'selfsigned.key'))
  ? { key: fs.readFileSync(path.join(certsDir, 'selfsigned.key')), cert: fs.readFileSync(path.join(certsDir, 'selfsigned.crt')) }
  : undefined

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    https: httpsConfig,
    host: '0.0.0.0',
    port: 3000,
    hmr: {
      // Explicit HMR config stabilises the WebSocket on mobile with self-signed certs
      protocol: httpsConfig ? 'wss' : 'ws',
      port: 3000,
    },
    proxy: {
      '/api': 'http://localhost:8080',
      '/ws': { target: 'ws://localhost:8080', ws: true },
    },
  },
  optimizeDeps: {
    // Work around TailwindCSS v4 HMR cache invalidation bug
    exclude: ['@tailwindcss/vite'],
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test-setup.js',
  },
})
