<script setup lang="ts">
/**
 * NewsModal.vue — модалка с полной информацией о новости (по клику на
 * золотой маркер графика цены). Содержимое по ТЗ:
 *  - заголовок title, текст content, FIGI инструмента;
 *  - саммари от ИИ ai_text_summary;
 *  - РАЗВЁРНУТАЯ аналитика из ai_raw_response (JSONB): executive_summary,
 *    fundamental/technical/macro/behavioral/quantitative/sector анализ,
 *    synergy_insights, practical_conclusions и queries модели — парсер и
 *    словари подписей в types/aiAnalysis.ts;
 *  - оценки ИИ в ВИЗУАЛИЗАЦИИ БЕЗ ЦИФР:
 *      Sentiment   — прогресс-бар красный → зелёный;
 *      Relevance   — прогресс-бар серый → золотой;
 *      Confidence  — прогресс-бар серый → золотой;
 *      Expected Impact — цветовой индикатор (красный/жёлтый/зелёный);
 *  - финансовые данные: close_price, depth, volume / volume_buy / volume_sell.
 * Дизайн: светлый фон, золотые акценты, элегантная типографика, без теней.
 */
import { computed, ref } from 'vue'
import type { MarketDataItem } from '../types/market'
import {
  confidenceBadge,
  fairValueBadge,
  overshootBadge,
  parseAiRawAnalysis,
  reactionBadge,
  type AiRawAnalysis,
  type Badge,
} from '../types/aiAnalysis'

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

/* ---------------------- Развёрнутая аналитика (ai_raw_response) ------------ */

/** Чистим секцию от незаполненных полей — UI рендерит только непустое. */
function prune<T extends object>(o: T): T {
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(o)) {
    if (v === undefined || v === null) continue
    if (Array.isArray(v) && v.length === 0) continue
    out[k] = v
  }
  return out as T
}

/**
 * Разбор JSONB ai_raw_response (толерантный: объект или JSON-строка,
 * историческое написание колонки ai_raw_responce тоже поддерживается).
 */
const rawAnalysis = computed<AiRawAnalysis | null>(() => {
  const it = props.news
  if (!it) return null
  const parsed = parseAiRawAnalysis(it.ai_raw_response ?? it.ai_raw_responce ?? null)
  if (!parsed) return null
  const cleaned: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(parsed)) {
    if (v === undefined || v === null) continue
    if (typeof v === 'object' && !Array.isArray(v)) {
      const pruned = prune(v as Record<string, unknown>)
      if (Object.keys(pruned).length > 0) cleaned[k] = pruned
    } else {
      cleaned[k] = v
    }
  }
  return Object.keys(cleaned).length > 0 ? (cleaned as AiRawAnalysis) : null
})

/** Русские заголовки секций raw-ответа (порядок = приоритет чтения). */
const SECTION_TITLES: Array<{ key: keyof AiRawAnalysis; title: string }> = [
  { key: 'executive_summary', title: 'Главное' },
  { key: 'practical_conclusions', title: 'Практические выводы' },
  { key: 'technical_analysis', title: 'Технический анализ' },
  { key: 'fundamental_analysis', title: 'Фундаментальный анализ' },
  { key: 'macro_analysis', title: 'Макроэкономика' },
  { key: 'behavioral_analysis', title: 'Поведение рынка' },
  { key: 'quantitative_analysis_and_risks', title: 'Количественная оценка и риски' },
  { key: 'sector_and_competitive_analysis', title: 'Отрасли и конкуренция' },
  { key: 'synergy_insights', title: 'Синергия и слепые зоны' },
]

interface SectionView {
  title: string
  paragraphs: Array<{ label: string; text: string }>
  lists: Array<{ label: string; items: string[] }>
  badges: Badge[]
}

const FIELD_LABELS: Record<string, string> = {
  essence: 'Суть события',
  key_conclusion: 'Ключевой вывод',
  macro_indicators_impact: 'Влияние макроиндикаторов',
  transmission_mechanisms: 'Трансмиссионные механизмы',
  scenarios: 'Торговые сценарии',
  key_levels: 'Ключевые уровни',
  risk_management: 'Риск-менеджмент',
  volume_analysis: 'Анализ объёмов',
  usd_rub_specifics: 'Специфика USD/RUB',
  volatility_regime: 'Режим волатильности',
  indicators_behavior: 'Поведение индикаторов',
  intermarket_analysis: 'Межрыночный анализ',
  price_pattern_impact: 'Влияние ценовых паттернов',
  operational_checklist: 'Операционный чек-лист',
  applicable_instruments: 'Применимые инструменты',
  trading_recommendations: 'Торговые рекомендации',
  reasoning: 'Логика вывода',
  financial_impact: 'Финансовое влияние',
  signal_vs_noise: 'Сигнал vs шум',
  volatility_impact: 'Влияние на волатильность',
  correlation_changes: 'Изменения корреляций',
  competitive_impact: 'Конкурентное влияние',
  supply_chain_impact: 'Влияние на цепочки поставок',
}

const LIST_LABELS: Record<string, string> = {
  applied_frameworks: 'Применённые фреймворки',
  applied_models: 'Применённые модели',
  cognitive_biases: 'Когнитивные искажения',
  affected_entities: 'Затронутые компании',
  applied_methodologies: 'Методологии оценки',
  blind_spots: 'Слепые зоны',
  macro_trend_links: 'Связи с макротрендами',
  secondary_effects: 'Вторичные эффекты',
  suggested_additional_data: 'Дополнительные данные',
  key_takeaways: 'Ключевые тезисы',
  events_to_watch: 'События под наблюдением',
  revision_triggers: 'Триггеры пересмотра',
  key_risks: 'Ключевые риски',
  losers: 'Пострадавшие',
  beneficiaries: 'Выгодоприобретатели',
}

/** Enum-поля выводим бейджами, а не «сырым» текстом. */
const BADGE_FIELDS = new Set([
  'confidence_level',
  'market_reaction_type',
  'overshooting_probability',
  'fair_value_assessment',
])

function collectBadges(src: Record<string, unknown>): Badge[] {
  const out: Badge[] = []
  const push = (b: Badge | null): void => { if (b) out.push(b) }
  push(confidenceBadge(typeof src['confidence_level'] === 'string' ? src['confidence_level'] : undefined))
  push(reactionBadge(typeof src['market_reaction_type'] === 'string' ? src['market_reaction_type'] : undefined))
  push(overshootBadge(typeof src['overshooting_probability'] === 'string' ? src['overshooting_probability'] : undefined))
  push(fairValueBadge(typeof src['fair_value_assessment'] === 'string' ? src['fair_value_assessment'] : undefined))
  return out
}

function buildSection(title: string, body: Record<string, unknown>): SectionView {
  const paragraphs: SectionView['paragraphs'] = []
  const lists: SectionView['lists'] = []
  for (const [field, value] of Object.entries(body)) {
    if (BADGE_FIELDS.has(field)) continue
    if (typeof value === 'string') {
      paragraphs.push({ label: FIELD_LABELS[field] ?? field, text: value })
    } else if (Array.isArray(value)) {
      lists.push({ label: LIST_LABELS[field] ?? field, items: value.filter((x): x is string => typeof x === 'string') })
    }
  }
  return { title, paragraphs, lists, badges: collectBadges(body) }
}

const sections = computed<SectionView[]>(() => {
  const analysis = rawAnalysis.value
  if (!analysis) return []
  const out: SectionView[] = []
  for (const { key, title } of SECTION_TITLES) {
    const body = analysis[key]
    if (!body || typeof body !== 'object' || Array.isArray(body)) continue
    const view = buildSection(title, body as Record<string, unknown>)
    if (view.paragraphs.length === 0 && view.lists.length === 0 && view.badges.length === 0) continue
    out.push(view)
  }
  return out
})

/** Ключевые запросы модели (queries) — компактный список над блоками анализа. */
const queries = computed<string[]>(() => rawAnalysis.value?.queries ?? [])

/** Сворачивание развёрнутого анализа (в модалке по умолчанию свёрнут). */
const rawOpen = ref(false)

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

        <!-- Развёрнутая структура из ai_raw_response (JSONB) -->
        <section v-if="sections.length > 0 || queries.length > 0" class="section raw-analysis">
          <button
            type="button"
            class="raw-toggle"
            :aria-expanded="rawOpen"
            @click="rawOpen = !rawOpen"
          >
            <span class="raw-toggle-title">Развёрнутый анализ ИИ</span>
            <span class="raw-toggle-hint">{{ rawOpen ? 'Свернуть' : `Показать (${sections.length} блоков)` }}</span>
          </button>

          <div v-show="rawOpen" class="raw-body">
            <ul v-if="queries.length > 0" class="queries">
              <li v-for="(q, i) in queries" :key="i" class="query">{{ q }}</li>
            </ul>

            <article v-for="(sec, i) in sections" :key="i" class="raw-section">
              <h4 class="raw-section-title">{{ sec.title }}</h4>

              <div v-if="sec.badges.length > 0" class="badges">
                <span
                  v-for="(b, j) in sec.badges"
                  :key="j"
                  class="badge"
                  :class="`badge--${b.tone}`"
                >{{ b.label }}</span>
              </div>

              <dl v-if="sec.paragraphs.length > 0" class="fields">
                <template v-for="(p, k) in sec.paragraphs" :key="k">
                  <dt class="field-label">{{ p.label }}</dt>
                  <dd class="field-value">{{ p.text }}</dd>
                </template>
              </dl>

              <div v-for="(list, m) in sec.lists" :key="`l-${m}`" class="list-block">
                <span class="field-label">{{ list.label }}</span>
                <ul class="chips">
                  <li v-for="(item, n) in list.items" :key="n" class="chip">{{ item }}</li>
                </ul>
              </div>
            </article>
          </div>
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
  /* Тоже поверх стековых контекстов секций; модалка выше дропдаунов. */
  z-index: var(--z-overlay);
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

/* ---------- Блок «Развёрнутый анализ ИИ» (ai_raw_response) ---------- */
.raw-analysis {
  border-top: 1px solid var(--color-platinum);
  padding-top: var(--space-sm);
}

.raw-toggle {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-sm);
  width: 100%;
  padding: 0;
  background: none;
  border: none;
  cursor: pointer;
  text-align: left;
}

.raw-toggle-title {
  font-size: var(--fs-micro);
  font-weight: var(--fw-medium);
  letter-spacing: var(--ls-ultra);
  text-transform: uppercase;
  color: var(--color-gold);
}

.raw-toggle-hint {
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  color: var(--color-grey-light);
}

.raw-body {
  margin-top: var(--space-sm);
}

.queries {
  list-style: none;
  margin: 0 0 var(--space-md);
  padding: var(--space-xs) var(--space-sm);
  border-left: 2px solid var(--color-platinum);
  background: var(--color-platinum-soft);
}

.query {
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  line-height: var(--lh-normal);
  color: var(--color-grey);
  padding: 2px 0;
}

.raw-section {
  margin-bottom: var(--space-md);
  padding-bottom: var(--space-sm);
  border-bottom: 1px solid var(--color-platinum-soft);
}

.raw-section:last-child {
  margin-bottom: 0;
  padding-bottom: 0;
  border-bottom: none;
}

.raw-section-title {
  margin: 0 0 var(--space-xs);
  font-size: var(--fs-small);
  font-weight: var(--fw-regular);
  letter-spacing: var(--ls-tight);
  color: var(--color-ink);
}

.badges {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-xs);
  margin-bottom: var(--space-xs);
}

.badge {
  display: inline-block;
  padding: 2px 8px;
  font-size: var(--fs-micro);
  font-weight: var(--fw-medium);
  letter-spacing: var(--ls-wide);
  text-transform: uppercase;
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-platinum);
}

.badge--gold {
  color: var(--color-bg-elevated);
  background: var(--color-gold);
  border-color: var(--color-gold);
}

.badge--neutral {
  color: var(--color-ink);
  background: var(--color-platinum-soft);
}

.badge--dark {
  color: var(--color-bg-elevated);
  background: var(--color-ink);
  border-color: var(--color-ink);
}

.fields {
  margin: 0;
}

.field-label {
  font-size: var(--fs-micro);
  font-weight: var(--fw-medium);
  letter-spacing: var(--ls-wide);
  text-transform: uppercase;
  color: var(--color-grey-light);
  margin-top: var(--space-xs);
}

.field-value {
  margin: 2px 0 0;
  font-size: var(--fs-small);
  font-weight: var(--fw-light);
  line-height: var(--lh-normal);
  color: var(--color-ink-soft);
}

.list-block {
  margin-top: var(--space-sm);
}

.chips {
  list-style: none;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-xs);
  margin: var(--space-xs) 0 0;
  padding: 0;
}

.chip {
  padding: 3px 10px;
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  color: var(--color-ink-soft);
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-platinum);
  border-radius: var(--radius-sm);
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