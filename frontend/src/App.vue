<script setup>
import { computed, ref } from 'vue'
import NewsAnalyzerForm from './components/NewsAnalyzerForm.vue'

// Базовый URL контейнера n8n во внутренней docker-сети app_net.
// Берётся из VITE_N8N_BASE_URL (см. docker-compose.yml); по умолчанию —
// http://n8n:5678/, т.к. внутри сети app_net 127.0.0.1 указывает не на n8n.
const n8nBase = (import.meta.env.VITE_N8N_BASE_URL || 'http://n8n:5678/').replace(/\/+$/, '') + '/'

// Если страница открыта в браузере НЕ на том же хосте, где живёт n8n по base-URL
// (например, frontend доступен по localhost:5173, а base — http://n8n:5678 —
// браузер разрешить не может), идём через прокси dev-сервера Vite «/n8n-api»
// (см. vite.config.js) — он работает из любого браузера.
function resolveBaseUrl(base) {
  if (typeof window === 'undefined') return base
  try {
    const b = new URL(base, window.location.href)
    const here = window.location.hostname
    const sameHost = b.hostname === here ||
      (b.hostname === 'localhost' && ['127.0.0.1', '::1', '[::1]'].includes(here)) ||
      (['127.0.0.1', '::1', '[::1]'].includes(b.hostname) && here === 'localhost')
    if (!sameHost) return '/n8n-api/'
  } catch {
    /* оставляем base как есть */
  }
  return base
}

const effectiveBase = resolveBaseUrl(n8nBase)

// Путь вебхука в n8n (имя «news_analizer» — такое же, как в workflow, это не опечатка)
const webhookPath = 'news_analizer'

// Режим вызова: 'live' → /webhook/… (активированный workflow),
//               'test' → /webhook-test/… (тестовый запуск «Execute workflow»).
// Начальное значение — из окружения (VITE_N8N_WEBHOOK_MODE), по умолчанию test.
const mode = ref(import.meta.env.VITE_N8N_WEBHOOK_MODE === 'live' ? 'live' : 'test')

const webhookUrl = computed(() => `${effectiveBase}${mode.value === 'test' ? 'webhook-test' : 'webhook'}/${webhookPath}`)

function setMode(m) {
  mode.value = m
}
</script>

<template>
  <main class="page">
    <header class="page-header">
      <h1>Анализатор рыночных новостей</h1>
      <p class="subtitle">
        Заполните карточку новости и нажмите «Анализировать» — данные уйдут
        в микросервис через n8n-вебхук и сохранятся в
        <code>market_news_ml_dataset</code>.
      </p>

      <div class="mode-row">
        <span class="mode-label">Режим вебхука:</span>
        <div class="mode-toggle" role="radiogroup" aria-label="Режим вебхука">
          <button
            type="button"
            :class="['mode-btn', { active: mode === 'test' }]"
            @click="setMode('test')"
          >
            webhook-test
          </button>
          <button
            type="button"
            :class="['mode-btn', { active: mode === 'live' }]"
            @click="setMode('live')"
          >
            webhook
          </button>
        </div>
      </div>

      <p class="webhook">URL вебхука: <code>{{ webhookUrl }}</code></p>
      <p v-if="mode === 'test'" class="hint">
        Тестовый режим: сначала нажмите «Execute workflow» в редакторе n8n —
        эндпоинт <code>/webhook-test/…</code> живёт только до конца тестового запуска.
      </p>
      <p v-else class="hint">
        Рабочий режим: workflow в n8n должен быть активирован (переключатель
        Active) — тогда работает <code>/webhook/…</code>.
      </p>
    </header>

    <NewsAnalyzerForm :webhook-url="webhookUrl" />
  </main>
</template>

<style scoped>
.page {
  max-width: 720px;
  margin: 0 auto;
  padding: 32px 20px 64px;
}
.page-header h1 {
  margin: 0 0 8px;
  font-size: 28px;
}
.subtitle {
  margin: 0 0 8px;
  color: #5b6472;
}
.webhook {
  margin: 0;
  font-size: 13px;
  color: #8a93a3;
}
.mode-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 0 8px;
}
.mode-label {
  font-size: 13px;
  font-weight: 600;
  color: #303846;
}
.mode-toggle {
  display: inline-flex;
  border: 1px solid #c7ced9;
  border-radius: 8px;
  overflow: hidden;
}
.mode-btn {
  border: none;
  background: #f4f6fa;
  color: #5b6472;
  font: inherit;
  font-size: 13px;
  padding: 6px 14px;
  cursor: pointer;
}
.mode-btn.active {
  background: #4f7cff;
  color: #fff;
  font-weight: 600;
}
.hint {
  margin: 0 0 8px;
  font-size: 12px;
  color: #8a93a3;
}
code {
  background: #eef1f5;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
}
</style>
