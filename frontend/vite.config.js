import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig(({ mode: viteMode }) => {
  const env = loadEnv(viteMode, process.cwd(), '')
  // Куда проксировать вызовы вебхуков из браузера (путь /n8n-api).
  // По умолчанию — контейнер n8n по проброшенному порту на хосте.
  const n8nProxyTarget = env.N8N_PROXY_TARGET || 'http://localhost:5678'

  return {
    plugins: [vue()],
    server: {
      host: true,      // слушать 0.0.0.0 внутри контейнера
      port: 5173,
      proxy: {
        // Браузер не знает docker-имя «n8n», поэтому запросы вида
        // /n8n-api/webhook/... и /n8n-api/webhook-test/... dev-сервер Vite
        // переправляет на n8n (см. resolveBaseUrl в App.vue).
        '/n8n-api': {
          target: n8nProxyTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/n8n-api/, ''),
        },
      },
    },
  }
})
