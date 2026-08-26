import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        configure: (proxy, _options) => {
          // Suppress ECONNREFUSED spam when backend isn't ready yet
          proxy.on('error', (err, req, res) => {
            if (err.message?.includes('ECONNREFUSED')) {
              // Send 503 ourselves — prevents Vite's internal logger from printing the error
              if (res && typeof res.writeHead === 'function' && !res.headersSent) {
                // 必须返回 JSON，否则前端 SSE parser 会报 "is not valid JSON"
                res.writeHead(503, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ detail: 'Backend not ready' }));
              }
            } else {
              console.warn('[Vite Proxy Error]', err.message);
            }
          });
        },
      },
    },
  },
})
