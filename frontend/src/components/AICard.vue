<script setup lang="ts">
/**
 * AICard.vue — карточка с актуальной ИИ-аналитикой по выбранному FIGI:
 * показывает последнюю запись с непустым ai_text_summary (саммари +
 * визуальные оценки без цифр). Пустая/скрыта, если ИИ-аналитики нет.
 *
 * Дополнение: структурированный блок «Развёрнутый анализ ИИ», построенный
 * на основе сырого JSON-ответа модели (колонка ai_raw_response /
 * историческое написание ai_raw_responce). Типы и tolerant-парсер —
 * в types/aiAnalysis.ts (зеркало temp.json). Существующая вёрстка и
 * функционал сохранены полностью; новый блок только добавлен.
 */
import { computed, ref } from 'vue'
import type { MarketDataItem } from '../types/market'
import { hasAiSummary } from '../utils/chartData'
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

/* ---------------------- Сырой ответ ИИ (ai_raw_response) ------------------- */

/** Чистим объект от незаполненных секций — UI рендерит только непустое. */
function prune<T extends object>(o: T): T {
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(o)) {
    if (v === undefined || v === null) continue
    if (Array.isArray(v) && v.length === 0) continue
    out[k] = v
  }
  return out as T
}

/** Разбор обоих написаний колонки; при мусоре/отсутствии — null. */
const rawAnalysis = computed<AiRawAnalysis | null>(() => {
  const item = latest.value
  if (!item) return null
  const parsed = parseAiRawAnalysis(item.ai_raw_response ?? item.ai_raw_responce ?? null)
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

/** Список enum-полей, выводимых бейджами (не дублируем их текстом). */
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

/** Ключевые запросы модели (queries) — компактный список под шапкой блока. */
const queries = computed<string[]>(() => rawAnalysis.value?.queries ?? [])

/** Сворачивание «сырого» блока (по свёрнутому состоянию карточка компактнее). */
const rawOpen = ref(false)

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

    <!-- Развёрнутый структурированный анализ из ai_raw_response -->
    <div v-if="sections.length > 0" class="raw-analysis">
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

        <section v-for="(sec, i) in sections" :key="i" class="raw-section">
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
        </section>
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

/* ---------- Блок «Развёрнутый анализ ИИ» (ai_raw_response) ---------- */
.raw-analysis {
  margin-top: var(--space-md);
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
}

.raw-section:last-child {
  margin-bottom: 0;
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
</style>