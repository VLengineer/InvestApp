<script setup lang="ts">
/**
 * Страница «Анализатор новостей» в стиле Modern Platinum.
 * Логика вызова вебхука n8n не менялась; переработаны только стили:
 * hero-шапка с fade-in + slide-up, токены вместо хардкод-цветов,
 * секции появляются при скролле (composable useRevealOnScroll).
 */
import { computed, ref } from 'vue'
import NewsAnalyzerForm from '../components/NewsAnalyzerForm.vue'
import { useRevealOnScroll } from '../composables/useRevealOnScroll'

const { revealRef } = useRevealOnScroll()

// ЗАЧЕМ ПРОКСИ: VITE_* переменные «впекаются» в JS-бандл на этапе сборки и
// используются БРАУЗЕРОМ. Docker-имя «n8n» браузер не резолвит (оно живёт
// только внутри docker-сети app_net) → ERR_NAME_NOT_RESOLVED. Поэтому вызовы
// вебхуков из браузера ВСЕГДА идут через относительный путь /n8n-api/…:
// dev-сервер Vite проксирует их на контейнер n8n (см. vite.config.js и
// N8N_PROXY_TARGET в docker-compose.yml). Так фронт работает из любого браузера.
const PROXY_BASE = '/n8n-api/'

// Прямой base-URL n8n (для диагностики/редких случаев, когда браузер сам
// видит n8n, например n8n запущен на хосте без docker).
const n8nBase = (import.meta.env.VITE_N8N_BASE_URL || 'http://n8n:5678/').replace(/\/+$/, '') + '/'

// Браузер не может разрешить docker-имена вида «n8n» — это одно слово без точек.
function isUnresolvableInBrowser(hostname: string) {
  return !hostname.includes('.') && hostname !== 'localhost'
}

// Режим выбора URL: 'auto' — как описано выше (docker-имя → прокси),
// 'proxy' — всегда через /n8n-api/, 'direct' — всегда напрямую на base.
const urlModePref = import.meta.env.VITE_N8N_URL_MODE || 'auto'

function resolveBaseUrl(base: string) {
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
const mode = ref(import.meta.env.VITE_N8N_WEBHOOK_MODE === 'live' ? 'live' : 'test')

const webhookUrl = computed(() => `${effectiveBase}${mode.value === 'test' ? 'webhook-test' : 'webhook'}/${webhookPath}`)

function setMode(m: string) {
  mode.value = m
}
</script>

<template>
  <main ref="revealRef" class="analyzer-page">
    <!-- Hero-шапка: fade-in + slide-up при загрузке страницы -->
    <header class="hero">
      <p class="kicker animate-hero">Рыночные данные · ИИ-аналитика</p>
      <h1 class="hero-title animate-hero animate-hero-delay-1">Анализатор рыночных новостей</h1>
      <p class="hero-subtitle animate-hero animate-hero-delay-2">
        Заполните карточку новости и нажмите «Анализировать» — данные уйдут
        в микросервис через n8n-вебхук и сохранятся в
        <code>market_news_ml_dataset</code>.
      </p>
    </header>

    <!-- Секции появляются при скролле (IntersectionObserver) -->
    <section class="section reveal">
      <div class="mode-row">
        <span class="mode-label">Режим вебхука</span>
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
    </section>

    <section class="section reveal">
      <NewsAnalyzerForm :webhook-url="webhookUrl" :auth-token="authToken" />
    </section>
  </main>
</template>

<style scoped>
/* Только токены из tokens.css — никаких хардкод-цветов. */
.analyzer-page {
  max-width: var(--container-max);
  margin: 0 auto;
  padding: var(--space-lg) var(--container-padding) var(--space-xl);
}

/* ---------- Hero ---------- */
.hero {
  margin-bottom: var(--space-lg);
}

.kicker {
  font-size: var(--fs-micro);
  font-weight: var(--fw-medium);
  letter-spacing: var(--ls-ultra);
  text-transform: uppercase;
  color: var(--color-gold);
  margin-bottom: var(--space-sm);
}

.hero-title {
  font-size: var(--fs-h2);
  font-weight: var(--fw-light);
  line-height: var(--lh-tight);
  letter-spacing: var(--ls-tight);
  color: var(--color-ink);
  margin-bottom: var(--space-sm);
}

.hero-subtitle {
  max-width: 640px;
  font-size: var(--fs-body);
  font-weight: var(--fw-light);
  line-height: var(--lh-loose);
  color: var(--color-grey);
}

/* ---------- Секции ---------- */
.section {
  margin-top: var(--space-md);
}

.mode-row {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  margin-bottom: var(--space-sm);
}

.mode-label {
  font-size: var(--fs-micro);
  font-weight: var(--fw-medium);
  letter-spacing: var(--ls-wide);
  text-transform: uppercase;
  color: var(--color-grey-light);
}

/* Сегментированный переключатель: платина в покое, золото — активный сегмент */
.mode-toggle {
  display: inline-flex;
  border: 1px solid var(--color-platinum);
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: var(--color-bg-elevated);
}

.mode-btn {
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  letter-spacing: var(--ls-tight);
  padding: var(--space-xs) var(--space-sm);
  color: var(--color-grey);
  cursor: pointer;
  transition:
    color var(--duration-fast) var(--ease-out),
    background-color var(--duration-fast) var(--ease-out);
}

.mode-btn:hover {
  color: var(--color-ink);
  background: var(--color-platinum-soft);
}

.mode-btn.active {
  background: var(--color-gold);
  color: var(--color-bg-elevated);
  font-weight: var(--fw-medium);
}

.webhook {
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  color: var(--color-grey-light);
}

.hint {
  margin-top: var(--space-xs);
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  line-height: var(--lh-normal);
  color: var(--color-grey-light);
}

code {
  background: var(--color-platinum-soft);
  border: 1px solid var(--color-platinum);
  border-radius: var(--radius-sm);
  padding: 2px var(--space-xs);
  color: var(--color-ink-soft);
}

/* ---------- Адаптив ---------- */
@media (max-width: 1023px) {
  .analyzer-page {
    padding: var(--space-md) var(--space-md) var(--space-lg);
  }
}

@media (max-width: 640px) {
  .mode-row {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-xs);
  }
}
</style>
