import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig(({ mode: viteMode }) => {
  const env = loadEnv(viteMode, process.cwd(), '')
  const n8nProxyTarget = env.N8N_PROXY_TARGET || 'http://localhost:5678'

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
      },
    },
  }
})
