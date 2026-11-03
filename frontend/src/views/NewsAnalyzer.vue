<script setup lang="ts">
import { computed, ref } from 'vue'
// Существующая страница «Анализатор новостей»: функционально НЕ менялась —
// переезд из App.vue в views/ только для подключения к роутеру и общему лейауту.
// Добавлен только класс .analyzer-page (ширина контейнера под content-area).
import NewsAnalyzerForm from '../components/NewsAnalyzerForm.vue'

// ЗАЧЕМ ПРОКСИ: VITE_* переменные «впекаются» в JS-бандл на этапе сборки и
// используются БРАУЗЕРОМ. Docker-имя «n8n» браузер не резолвит (оно живёт
// только внутри docker-сети app_net) → ERR_NAME_NOT_RESOLVED. Поэтому вызовы
// вебхуков из браузера ВСЕГДА идут через относительный путь /n8n-api/…:
// dev-сервер Vite (работающий внутри контейнера frontend, где имя «n8n»
// разрешается) проксирует их на контейнер n8n (см. vite.config.js и
// N8N_PROXY_TARGET в docker-compose.yml). Так фронт работает из любого
// браузера — хоть localhost, хоть IP хоста, хоть удалённая машина.
const PROXY_BASE = '/n8n-api/'

// Прямой base-URL n8n (для диагностики/редких случаев, когда браузер сам
// видит n8n, например n8n запущен на хосте без docker).
const n8nBase = (import.meta.env.VITE_N8N_BASE_URL || 'http://n8n:5678/').replace(/\/+$/, '') + '/'

// Браузер не может разрешить docker-имена вида «n8n» — это одно слово без точек.
function isUnresolvableInBrowser(hostname) {
  return !hostname.includes('.') && hostname !== 'localhost'
}

// Режим выбора URL: 'auto' — как описано выше (docker-имя → прокси),
// 'proxy' — всегда через /n8n-api/, 'direct' — всегда напрямую на base.
const urlModePref = import.meta.env.VITE_N8N_URL_MODE || 'auto'

function resolveBaseUrl(base) {
  if (typeof window === 'undefined') return base
  if (urlModePref === 'proxy') return PROXY_BASE
  if (urlModePref === 'direct') return base
  try {
    const b = new URL(base, window.location.href)
    // docker-имя или чужой хост → через прокси Vite
    if (isUnresolvableInBrowser(b.hostname)) return PROXY_BASE
    const here = window.location.hostname
    const sameHost = b.hostname === here ||
      (b.hostname === 'localhost' && ['127.0.0.1', '::1', '[::1]'].includes(here)) ||
      (['127.0.0.1', '::1', '[::1]'].includes(b.hostname) && here === 'localhost')
    if (!sameHost) return PROXY_BASE
  } catch {
    /* оставляем base как есть */
  }
  return base
}

// Токен для запросов к n8n (Authorization: Bearer …). Приходит из корневого
// .env через docker-compose: N8N_AUTH_TOKEN → VITE_N8N_AUTH_TOKEN.
// Пустой значение — заголовок авторизации не отправляется вовсе.
const authToken = import.meta.env.VITE_N8N_AUTH_TOKEN || ''

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
  <main class="analyzer-page">
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

    <NewsAnalyzerForm :webhook-url="webhookUrl" :auth-token="authToken" />
  </main>
</template>

<style scoped>
.analyzer-page {
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
