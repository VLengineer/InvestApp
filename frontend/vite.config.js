import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig(({ mode: viteMode }) => {
  const env = loadEnv(viteMode, process.cwd(), '')
  const n8nProxyTarget = env.N8N_PROXY_TARGET || 'http://localhost:5678'
  // BFF для дашборда (backend-frontend): REST /api/* + WebSocket /ws/market-updates.
  // В docker-сети контейнер доступен по имени backend-frontend:8300 (см. docker-compose.yml).
  const marketProxyTarget = env.MARKET_API_PROXY_TARGET || 'http://localhost:8300'

  return {
    plugins: [vue()],
    server: {
      host: true,      // слушать 0.0.0.0 внутри контейнера
      port: 5173,
      proxy: {
        '/n8n-api': {
          target: n8nProxyTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/n8n-api/, ''),
        },
        // REST финансового дашборда → backend-frontend (тот же паттерн, что /n8n-api:
        // браузер не резолвит docker-имена, все вызовы идут через Vite-прокси)
        '/api': {
          target: marketProxyTarget,
          changeOrigin: true,
        },
        // WebSocket real-time рынка → backend-frontend (ws:true обязателен для WS)
        '/ws': {
          target: marketProxyTarget.replace(/^http/, 'ws'),
          ws: true,
          changeOrigin: true,
        },
      },
    },
  }
})
