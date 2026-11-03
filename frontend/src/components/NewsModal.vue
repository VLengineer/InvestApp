<script setup lang="ts">
/**
 * NewsModal.vue — модалка с полной информацией о новости (по клику на
 * золотой маркер графика цены). Содержимое по ТЗ:
 *  - заголовок title, текст content, FIGI инструмента;
 *  - саммари от ИИ ai_text_summary;
 *  - оценки ИИ в ВИЗУАЛИЗАЦИИ БЕЗ ЦИФР:
 *      Sentiment   — прогресс-бар красный → зелёный;
 *      Relevance   — прогресс-бар серый → золотой;
 *      Confidence  — прогресс-бар серый → золотой;
 *      Expected Impact — цветовой индикатор (красный/жёлтый/зелёный);
 *  - финансовые данные: close_price, depth, volume / volume_buy / volume_sell.
 * Дизайн: светлый фон, золотые акценты, элегантная типографика, без теней.
 */
import { computed } from 'vue'
import type { MarketDataItem } from '../types/market'

const props = defineProps<{
  /** Данные новости (полная запись из GET /api/market/news/{id}). */
  news: MarketDataItem | null
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

/** Ограничение значения в [0..1]. */
function clamp01(v: number | null | undefined): number {
  if (v === null || v === undefined || !Number.isFinite(v)) return 0
  return Math.min(1, Math.max(0, v))
}

/**
 * Sentiment ∈ [-1, 1] → позиция на шкале 0..100% и цвет красный→зелёный.
 * Возвращаем ТОЛЬКО визуальные параметры — цифры не показываем (ТЗ).
 */
/** Палитра шкал — из CSS-переменных tokens.css (Modern Platinum). */
function cssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

/** Sentiment ∈ [-1, 1] → позиция на шкале 0..100%; цвет по палитре стиля. */
const sentiment = computed(() => {
  const s = props.news?.ai_sentiment_score
  if (s === null || s === undefined || !Number.isFinite(s)) return null
  const pos = ((clamp01((s + 1) / 2)) * 100).toFixed(0) // -1→0%, +1→100%
  const p = Number(pos)
  const color =
    p < 50 ? cssVar('--color-platinum-dark', '#A8A8A8')
    : p > 50 ? cssVar('--color-ink', '#111111')
    : cssVar('--color-gold', '#B8935A')
  return { pos: `${pos}%`, color }
})

/** Позиция серо-золотого прогресс-бара (relevance/confidence ∈ [0..1]). */
function goldBar(v: number | null | undefined): string | null {
  if (v === null || v === undefined || !Number.isFinite(v)) return null
  return `${(clamp01(v) * 100).toFixed(0)}%`
}

const relevance = computed(() => goldBar(props.news?.ai_relevance_score))
const confidence = computed(() => goldBar(props.news?.ai_confidence))

/**
 * Expected Impact: интерпретируем шкалу 0..1 как силу влияния:
 * <0.34 — низкий (зелёный), <0.67 — средний (жёлтый), иначе высокий (красный).
 */
const impact = computed(() => {
  const v = props.news?.ai_expected_impact
  if (v === null || v === undefined || !Number.isFinite(v)) return null
  const c = clamp01(v)
  // Шкала силы влияния — тона из палитры Modern Platinum (без ярких цветов)
  if (c < 1 / 3) return { label: 'Низкое влияние', color: cssVar('--color-platinum-dark', '#A8A8A8') }
  if (c < 2 / 3) return { label: 'Среднее влияние', color: cssVar('--color-gold', '#B8935A') }
  return { label: 'Высокое влияние', color: cssVar('--color-ink', '#111111') }
})

const hasAi = computed(
  () => !!props.news && (!!sentiment.value || !!relevance.value || !!confidence.value || !!impact.value),
)

/** Форматирование денег/объёмов для блока финансовых данных. */
function fmt(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '—'
  return n.toLocaleString('ru-RU')
}

const closePrice = computed(() => {
  const it = props.news
  if (!it) return '—'
  const price = it.close_price_units ?? it.close_price
  const cur = it.price_currency ? ` ${it.price_currency}` : ''
  return Number.isFinite(price) ? `${fmt(price)}${cur}` : '—'
})

function onOverlayClick(ev: MouseEvent) {
  // Закрытие только по клику на затемнённый оверлей, не на карточку
  if (ev.target === ev.currentTarget) emit('close')
}
</script>

<template>
  <div v-if="news" class="overlay" @click="onOverlayClick">
    <div class="modal card" role="dialog" aria-modal="true" aria-label="Новость">
      <header class="head">
        <div>
          <p class="kicker">Новость рынка · {{ news.figi || '—' }}</p>
          <h2 class="title">{{ news.title || 'Без заголовка' }}</h2>
          <p v-if="news.ts" class="meta">
            {{ new Date(news.ts).toLocaleString('ru-RU') }}
            <span v-if="news.source"> · {{ news.source }}</span>
          </p>
        </div>
        <button type="button" class="close" aria-label="Закрыть" @click="emit('close')">✕</button>
      </header>

      <div class="body">
        <!-- Текст новости -->
        <section v-if="news.content" class="section">
          <h3 class="section-title">Текст новости</h3>
          <p class="content-text">{{ news.content }}</p>
        </section>

        <!-- Саммари от ИИ -->
        <section v-if="news.ai_text_summary" class="section ai-summary">
          <h3 class="section-title gold">Саммари от ИИ</h3>
          <p class="summary-text">{{ news.ai_text_summary }}</p>
        </section>

        <!-- Оценки ИИ: визуализация БЕЗ ЦИФР -->
        <section v-if="hasAi" class="section">
          <h3 class="section-title gold">Оценки ИИ</h3>

          <div v-if="sentiment" class="meter">
            <span class="meter-label">Sentiment</span>
            <div class="bar bar--gradient-red-green">
              <div class="bar-thumb" :style="{ left: sentiment.pos, background: sentiment.color }" />
            </div>
          </div>

          <div v-if="relevance" class="meter">
            <span class="meter-label">Relevance</span>
            <div class="bar">
              <div class="bar-fill fill-gold" :style="{ width: relevance }" />
            </div>
          </div>

          <div v-if="confidence" class="meter">
            <span class="meter-label">Confidence</span>
            <div class="bar">
              <div class="bar-fill fill-gold" :style="{ width: confidence }" />
            </div>
          </div>

          <div v-if="impact" class="meter meter--inline">
            <span class="meter-label">Expected Impact</span>
            <span class="impact-dot" :style="{ background: impact.color }" />
            <span class="impact-label">{{ impact.label }}</span>
          </div>
        </section>

        <!-- Финансовые данные -->
        <section class="section">
          <h3 class="section-title">Финансовые данные</h3>
          <dl class="fin-grid">
            <div><dt>Цена закрытия</dt><dd>{{ closePrice }}</dd></div>
            <div><dt>Глубина стакана</dt><dd>{{ fmt(news.depth) }}</dd></div>
            <div><dt>Объём</dt><dd>{{ fmt(news.volume) }}</dd></div>
            <div><dt>Объём покупок</dt><dd class="up">{{ fmt(news.volume_buy) }}</dd></div>
            <div><dt>Объём продаж</dt><dd class="down">{{ fmt(news.volume_sell) }}</dd></div>
          </dl>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Модалка новости: светлый фон, тонкие платиновые линии, золото — точечный
   акцент; радиусы 2px, тень только у «поднятого» слоя. Только токены. */
.overlay {
  position: fixed;
  inset: 0;
  z-index: 50;
  background: var(--color-overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-md);
  animation: overlay-fade var(--duration-fast) var(--ease-out) both;
}

.card {
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-platinum);
  border-top: 2px solid var(--color-gold);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-medium); /* тень поднятого слоя — допустима */
  width: min(680px, 100%);
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  animation: modal-rise var(--duration-normal) var(--ease-out) both;
}

.head {
  display: flex;
  justify-content: space-between;
  gap: var(--space-sm);
  padding: var(--space-md) var(--space-md) var(--space-sm);
  border-bottom: 1px solid var(--color-platinum);
}

.kicker {
  margin: 0 0 4px;
  font-size: var(--fs-micro);
  font-weight: var(--fw-medium);
  letter-spacing: var(--ls-wide);
  text-transform: uppercase;
  color: var(--color-gold);
}

.title {
  margin: 0;
  font-size: var(--fs-h3);
  font-weight: var(--fw-light);
  line-height: var(--lh-tight);
  letter-spacing: var(--ls-tight);
  color: var(--color-ink);
}

.meta {
  margin: 6px 0 0;
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  color: var(--color-grey-light);
}

.close {
  align-self: flex-start;
  border: 1px solid var(--color-platinum);
  background: var(--color-bg-elevated);
  color: var(--color-grey);
  border-radius: var(--radius-sm);
  width: 32px;
  height: 32px;
  cursor: pointer;
  font-size: var(--fs-small);
  transition:
    color var(--duration-fast) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out);
}

.close:hover {
  color: var(--color-gold-hover);
  border-color: var(--color-gold);
}

.body {
  overflow-y: auto;
  padding: var(--space-sm) var(--space-md) var(--space-md);
}

.section {
  margin-top: var(--space-sm);
}

.section-title {
  margin: 0 0 var(--space-xs);
  font-size: var(--fs-micro);
  font-weight: var(--fw-medium);
  letter-spacing: var(--ls-wide);
  text-transform: uppercase;
  color: var(--color-grey-light);
}

.section-title.gold {
  color: var(--color-gold);
}

.content-text,
.summary-text {
  margin: 0;
  font-size: var(--fs-small);
  font-weight: var(--fw-light);
  line-height: var(--lh-normal);
  color: var(--color-ink-soft);
}

.ai-summary {
  border-left: 2px solid var(--color-gold);
  padding-left: var(--space-sm);
}

/* Прогресс-бары оценок ИИ — без цифр */
.meter {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  margin-bottom: 10px;
}

.meter-label {
  flex: 0 0 120px;
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  color: var(--color-grey);
}

.bar {
  position: relative;
  flex: 1;
  height: 6px;
  border-radius: var(--radius-none);
  background: var(--color-platinum-soft);
  border: 1px solid var(--color-platinum);
}

/* Единственный допустимый градиент — приглушённая шкала стиля */
.bar--gradient-red-green {
  background: linear-gradient(90deg, var(--color-platinum-dark), var(--color-gold), var(--color-ink));
  border: none;
}

.bar-fill {
  height: 100%;
  border-radius: var(--radius-none);
}

.fill-gold {
  background: var(--color-gold);
}

.bar-thumb {
  position: absolute;
  top: -4px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  transform: translateX(-50%);
  border: 2px solid var(--color-bg-elevated);
}

.impact-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex: 0 0 12px;
}

.impact-label {
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  color: var(--color-ink-soft);
}

/* Финансовые данные */
.fin-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--space-xs);
  margin: 0;
}

.fin-grid > div {
  border: 1px solid var(--color-platinum);
  border-radius: var(--radius-sm);
  padding: 10px var(--space-sm);
  background: var(--color-platinum-soft);
}

.fin-grid dt {
  font-size: var(--fs-micro);
  letter-spacing: var(--ls-normal);
  text-transform: uppercase;
  color: var(--color-grey-light);
  margin-bottom: 4px;
}

.fin-grid dd {
  margin: 0;
  font-size: var(--fs-body);
  font-weight: var(--fw-light);
  color: var(--color-ink);
}

/* «Покупки/продажи» — тона палитры, без ярких цветов */
.fin-grid .up { color: var(--color-gold); }
.fin-grid .down { color: var(--color-platinum-dark); }

@media (max-width: 640px) {
  .overlay {
    padding: var(--space-sm);
  }

  .meter-label {
    flex-basis: 90px;
  }
}
</style>