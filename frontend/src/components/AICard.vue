<script setup lang="ts">
/**
 * AICard.vue — карточка с актуальной ИИ-аналитикой по выбранному FIGI:
 * показывает последнюю запись с непустым ai_text_summary (саммари +
 * визуальные оценки без цифр). Пустая/скрыта, если ИИ-аналитики нет.
 */
import { computed } from 'vue'
import type { MarketDataItem } from '../types/market'
import { hasAiSummary } from '../utils/chartData'

const props = defineProps<{
  /** История записей текущего FIGI (из Dashboard.vue). */
  data: MarketDataItem[]
}>()

/** Последняя запись с ИИ-саммари (данные отсортированы по времени). */
const latest = computed<MarketDataItem | null>(() => {
  for (let i = props.data.length - 1; i >= 0; i--) {
    if (hasAiSummary(props.data[i])) return props.data[i]
  }
  return null
})

/** Ширина серо-золотого прогресс-бара из значения [0..1] — без цифр. */
function barWidth(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '0%'
  return `${Math.min(100, Math.max(0, v * 100)).toFixed(0)}%`
}

/** Палитра шкалы sentiment — из CSS-переменных tokens.css (Modern Platinum). */
function cssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

/** Sentiment [-1..1] → позиция маркера; цвет: платина → золото → чёрный. */
const sentiment = computed(() => {
  const s = latest.value?.ai_sentiment_score
  if (s === null || s === undefined || !Number.isFinite(s)) return null
  const pos = Math.min(100, Math.max(0, ((s + 1) / 2) * 100))
  const color =
    pos < 50 ? cssVar('--color-platinum-dark', '#A8A8A8')
    : pos > 50 ? cssVar('--color-ink', '#111111')
    : cssVar('--color-gold', '#B8935A')
  return { pos: `${pos.toFixed(0)}%`, color }
})
</script>

<template>
  <div v-if="latest" class="ai-card card pl-card pl-card--accent">
    <div class="head">
      <h3 class="title">Аналитика ИИ</h3>
      <span v-if="latest.ts" class="meta">{{ new Date(latest.ts).toLocaleString('ru-RU') }}</span>
    </div>

    <p class="summary">{{ latest.ai_text_summary }}</p>

    <div class="meters">
      <div v-if="sentiment" class="meter">
        <span class="label">Sentiment</span>
        <div class="bar gradient">
          <span class="thumb" :style="{ left: sentiment.pos, background: sentiment.color }" />
        </div>
      </div>
      <div class="meter">
        <span class="label">Relevance</span>
        <div class="bar"><span class="fill" :style="{ width: barWidth(latest.ai_relevance_score) }" /></div>
      </div>
      <div class="meter">
        <span class="label">Confidence</span>
        <div class="bar"><span class="fill" :style="{ width: barWidth(latest.ai_confidence) }" /></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Modern Platinum: flat-карточка с золотой линией слева (аналитический блок),
   радиусы 2px, без теней в покое. Только токены из tokens.css. */
.card {
  padding: var(--space-md);
}

.head {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  margin-bottom: var(--space-sm);
}

.kicker {
  font-size: var(--fs-micro);
  font-weight: var(--fw-medium);
  letter-spacing: var(--ls-ultra);
  text-transform: uppercase;
  color: var(--color-gold);
}

.meta {
  margin-left: auto;
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  color: var(--color-grey-light);
}

.title {
  margin: 0 0 var(--space-sm);
  font-size: var(--fs-h3);
  font-weight: var(--fw-light);
  line-height: var(--lh-tight);
  letter-spacing: var(--ls-tight);
  color: var(--color-ink);
}

.summary {
  margin: 0 0 var(--space-sm);
  font-size: var(--fs-body);
  font-weight: var(--fw-light);
  line-height: var(--lh-normal);
  color: var(--color-ink-soft);
}

.meter {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  margin-top: var(--space-xs);
}

.label {
  flex: 0 0 90px;
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  letter-spacing: var(--ls-tight);
  color: var(--color-grey);
}

.bar {
  position: relative;
  flex: 1;
  height: 4px;
  border-radius: var(--radius-none);
  background: var(--color-platinum-soft);
  border: 1px solid var(--color-platinum);
  overflow: visible;
}

/* Единственный допустимый градиент — «сигнал» от минимума к максимуму,
   приглушённые тона палитры (тёмный → золото → светлый). */
.bar.gradient {
  background: linear-gradient(90deg, var(--color-ink), var(--color-gold), var(--color-platinum));
  border: none;
}

.fill {
  display: block;
  height: 100%;
  background: var(--color-gold);
}

.thumb {
  position: absolute;
  top: -5px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  transform: translateX(-50%);
  background: var(--color-bg-elevated);
  border: 2px solid var(--color-ink);
}

.empty {
  font-size: var(--fs-small);
  font-weight: var(--fw-light);
  color: var(--color-grey-light);
}
</style>