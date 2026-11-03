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
const sentiment = computed(() => {
  const s = props.news?.ai_sentiment_score
  if (s === null || s === undefined || !Number.isFinite(s)) return null
  const pos = ((clamp01((s + 1) / 2)) * 100).toFixed(0) // -1→0%, +1→100%
  // Интерполяция HSV: красный (0°) → зелёный (120°)
  const hue = (Number(pos) / 100) * 120
  return { pos: `${pos}%`, color: `hsl(${hue}, 55%, 45%)` }
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
  if (c < 1 / 3) return { label: 'Низкое влияние', color: '#3E8E5A' }
  if (c < 2 / 3) return { label: 'Среднее влияние', color: '#D9B21A' }
  return { label: 'Высокое влияние', color: '#C0392B' }
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
/* Светлый фон, тонкие линии, золотые акценты; без градиентов-тени на карточке. */
.overlay {
  position: fixed;
  inset: 0;
  z-index: 50;
  background: rgba(26, 26, 26, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.card {
  background: #ffffff;
  border: 1px solid var(--color-platinum-dark, #b8b7b5);
  border-top: 2px solid var(--color-gold, #d4af37);
  border-radius: 8px;
  width: min(680px, 100%);
  max-height: 85vh;
  display: flex;
  flex-direction: column;
}

.head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 24px 12px;
  border-bottom: 1px solid var(--color-platinum, #e5e4e2);
}

.kicker {
  margin: 0 0 4px;
  font-size: 11px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--color-gold-dark, #a8871c);
}

.title {
  margin: 0;
  font-size: 19px;
  font-weight: 400;
  line-height: 1.3;
  color: var(--color-text-primary, #1a1a1a);
}

.meta {
  margin: 6px 0 0;
  font-size: 12px;
  font-weight: 300;
  color: var(--color-text-secondary, #6b6b6b);
}

.close {
  align-self: flex-start;
  border: 1px solid var(--color-platinum, #e5e4e2);
  background: #ffffff;
  color: var(--color-text-secondary, #6b6b6b);
  border-radius: 6px;
  width: 32px;
  height: 32px;
  cursor: pointer;
  font-size: 14px;
}

.close:hover {
  color: var(--color-gold-dark, #a8871c);
  border-color: var(--color-gold, #d4af37);
}

.body {
  overflow-y: auto;
  padding: 8px 24px 24px;
}

.section {
  margin-top: 18px;
}

.section-title {
  margin: 0 0 8px;
  font-size: 12px;
  font-weight: 400;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--color-text-secondary, #6b6b6b);
}

.section-title.gold {
  color: var(--color-gold-dark, #a8871c);
}

.content-text,
.summary-text {
  margin: 0;
  font-size: 14px;
  font-weight: 300;
  line-height: 1.6;
  color: var(--color-text-primary, #1a1a1a);
}

.ai-summary {
  border-left: 2px solid var(--color-gold, #d4af37);
  padding-left: 14px;
}

/* Прогресс-бары оценок ИИ — без цифр */
.meter {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.meter-label {
  flex: 0 0 120px;
  font-size: 13px;
  font-weight: 300;
  color: var(--color-text-secondary, #6b6b6b);
}

.bar {
  position: relative;
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: var(--color-platinum-light, #f5f5f4);
  border: 1px solid var(--color-platinum, #e5e4e2);
}

.bar--gradient-red-green {
  background: linear-gradient(90deg, #c0392b, #d9b21a, #3e8e5a);
  border: none;
}

.bar-fill {
  height: 100%;
  border-radius: 3px;
}

.fill-gold {
  background: linear-gradient(90deg, var(--color-platinum-dark, #b8b7b5), var(--color-gold, #d4af37));
}

.bar-thumb {
  position: absolute;
  top: -4px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  transform: translateX(-50%);
  border: 2px solid #ffffff;
}

.impact-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex: 0 0 12px;
}

.impact-label {
  font-size: 13px;
  font-weight: 300;
  color: var(--color-text-primary, #1a1a1a);
}

/* Финансовые данные */
.fin-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 10px;
  margin: 0;
}

.fin-grid > div {
  border: 1px solid var(--color-platinum, #e5e4e2);
  border-radius: 6px;
  padding: 10px 12px;
  background: var(--color-platinum-light, #f5f5f4);
}

.fin-grid dt {
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--color-text-secondary, #6b6b6b);
  margin-bottom: 4px;
}

.fin-grid dd {
  margin: 0;
  font-size: 15px;
  font-weight: 300;
  color: var(--color-text-primary, #1a1a1a);
}

.fin-grid .up { color: #3e8e5a; }
.fin-grid .down { color: #c0392b; }
</style>
