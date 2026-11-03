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

/** Sentiment [-1..1] → позиция маркера и цвет красный→зелёный. */
const sentiment = computed(() => {
  const s = latest.value?.ai_sentiment_score
  if (s === null || s === undefined || !Number.isFinite(s)) return null
  const pos = Math.min(100, Math.max(0, ((s + 1) / 2) * 100))
  return { pos: `${pos.toFixed(0)}%`, color: `hsl(${(pos / 100) * 120}, 55%, 45%)` }
})
</script>

<template>
  <div v-if="latest" class="ai-card card">
    <div class="head">
      <h3 class="title">Аналитика ИИ</h3>
      <span v-if="latest.ts" class="time">{{ new Date(latest.ts).toLocaleString('ru-RU') }}</span>
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
.card {
  background: #ffffff;
  border: 1px solid var(--color-platinum, #e5e4e2);
  border-left: 2px solid var(--color-gold, #d4af37);
  border-radius: 8px;
  padding: 16px;
}

.head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 8px;
}

.title {
  margin: 0;
  font-size: 13px;
  font-weight: 400;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--color-gold-dark, #a8871c);
}

.time {
  font-size: 12px;
  font-weight: 300;
  color: var(--color-text-secondary, #6b6b6b);
}

.summary {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 300;
  line-height: 1.55;
  color: var(--color-text-primary, #1a1a1a);
}

.meter {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
}

.label {
  flex: 0 0 90px;
  font-size: 12px;
  font-weight: 300;
  color: var(--color-text-secondary, #6b6b6b);
}

.bar {
  position: relative;
  flex: 1;
  height: 5px;
  border-radius: 3px;
  background: var(--color-platinum-light, #f5f5f4);
  border: 1px solid var(--color-platinum, #e5e4e2);
  overflow: visible;
}

.bar.gradient {
  background: linear-gradient(90deg, #c0392b, #d9b21a, #3e8e5a);
  border: none;
}

.fill {
  display: block;
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, var(--color-platinum-dark, #b8b7b5), var(--color-gold, #d4af37));
}

.thumb {
  position: absolute;
  top: -4px;
  width: 11px;
  height: 11px;
  border-radius: 50%;
  transform: translateX(-50%);
  border: 2px solid #fff;
}
</style>
