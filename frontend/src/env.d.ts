/// <reference types="vite/client" />

// Типы для Vite-переменных окружения, используемых фронтом.
interface ImportMetaEnv {
  readonly VITE_N8N_BASE_URL?: string
  readonly VITE_N8N_URL_MODE?: 'auto' | 'proxy' | 'direct'
  readonly VITE_N8N_AUTH_TOKEN?: string
  readonly VITE_N8N_WEBHOOK_MODE?: 'live' | 'test'
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>
  export default component
}
