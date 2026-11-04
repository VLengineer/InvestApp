/**
 * aiAnalysis.ts — TypeScript-модель «сырого» ответа ИИ (ai_raw_response /
 * историческое написание в БД — ai_raw_responce) из колонки JSONB таблицы
 * market_news_ml_dataset. Интерфейсы сгенерированы по образцу ./temp.json.
 *
 * Принципы:
 *  * строго типизированный «снимок» ожидаемой структуры (AiRawAnalysis);
 *  * tolerant-парсер parseAiRawAnalysis(): любое содержимое JSONB сводится
 *    к Partial-safe объекту без `any` — неизвестные поля не ломают UI;
 *  * словари русских подписей/цветов бейджей для ключевых enum-полей
 *    (confidence_level, market_reaction_type, fair_value_assessment и т.д.).
 */

/* ============================ Модель данных ================================ */

/** Блок executive_summary — суть события и главный вывод. */
export interface AiExecutiveSummary {
  essence?: string
  key_conclusion?: string
  /** HIGH | MEDIUM | LOW (иногда строчными) */
  confidence_level?: string
}

/** Блок macro_analysis — макроэкономика и каналы транзистивного влияния. */
export interface AiMacroAnalysis {
  applied_frameworks?: string[]
  macro_indicators_impact?: string
  transmission_mechanisms?: string
}

/** Блок technical_analysis — торговые сценарии и риск-менеджмент. */
export interface AiTechnicalAnalysis {
  scenarios?: string
  key_levels?: string
  risk_management?: string
  volume_analysis?: string
  usd_rub_specifics?: string
  volatility_regime?: string
  indicators_behavior?: string
  intermarket_analysis?: string
  price_pattern_impact?: string
  operational_checklist?: string
  applicable_instruments?: string
  trading_recommendations?: string
}

/** Блок behavioral_analysis — поведенческие модели толпы. */
export interface AiBehavioralAnalysis {
  applied_models?: string[]
  cognitive_biases?: string[]
  /** EMOTIONAL | RATIONAL | MIXED ... */
  market_reaction_type?: string
  /** HIGH | MEDIUM | LOW */
  overshooting_probability?: string
}

/** Блок fundamental_analysis — фундаментал и справедливая стоимость. */
export interface AiFundamentalAnalysis {
  reasoning?: string
  financial_impact?: string
  affected_entities?: string[]
  applied_methodologies?: string[]
  /** DECLINE | UPGRADE | UNCHANGED ... */
  fair_value_assessment?: string
}

/** Блок synergy_insights — перекрёстные инсайты анализа. */
export interface AiSynergyInsights {
  blind_spots?: string[]
  signal_vs_noise?: string
  macro_trend_links?: string[]
  secondary_effects?: string[]
  suggested_additional_data?: string[]
}

/** Блок practical_conclusions — практические выводы. */
export interface AiPracticalConclusions {
  key_takeaways?: string[]
  events_to_watch?: string[]
  revision_triggers?: string[]
}

/** Блок quantitative_analysis_and_risks — количественная оценка рисков. */
export interface AiQuantitativeAnalysis {
  key_risks?: string[]
  applied_models?: string[]
  volatility_impact?: string
  correlation_changes?: string
}

/** Блок sector_and_competitive_analysis — сектора, проигравшие и выгодоприобретатели. */
export interface AiSectorAnalysis {
  losers?: string[]
  beneficiaries?: string[]
  competitive_impact?: string
  supply_chain_impact?: string
}

/** Полный «сырой» ответ ИИ (зеркало temp.json). Все поля опциональны:
 *  модель может вернуть неполный JSON — UI должен это пережить. */
export interface AiRawAnalysis {
  queries?: string[]
  executive_summary?: AiExecutiveSummary
  macro_analysis?: AiMacroAnalysis
  technical_analysis?: AiTechnicalAnalysis
  behavioral_analysis?: AiBehavioralAnalysis
  fundamental_analysis?: AiFundamentalAnalysis
  synergy_insights?: AiSynergyInsights
  practical_conclusions?: AiPracticalConclusions
  quantitative_analysis_and_risks?: AiQuantitativeAnalysis
  sector_and_competitive_analysis?: AiSectorAnalysis
}

/* ============================== Парсер ==================================== */

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

function str(v: unknown): string | undefined {
  return typeof v === 'string' && v.trim() !== '' ? v : undefined
}

function strArray(v: unknown): string[] | undefined {
  if (!Array.isArray(v)) return undefined
  const out = v.filter((x): x is string => typeof x === 'string' && x.trim() !== '')
  return out.length > 0 ? out : undefined
}

function section<T extends object>(v: unknown, pick: (rec: Record<string, unknown>) => T | undefined): T | undefined {
  if (!isRecord(v)) return undefined
  return pick(v)
}

/**
 * Безопасное приведение значения колонки ai_raw_response(JSONB) к AiRawAnalysis.
 * Принимает уже распарсенный объект (бэкенд отдаёт dict) либо JSON-строку
 * (на случай, если провайдер сериализует JSONB как текст). Всё лишнее отбрасывается,
 * отсутствие блоков не считается ошибкой — возвращаем «что есть».
 */
export function parseAiRawAnalysis(raw: unknown): AiRawAnalysis | null {
  let obj: unknown = raw
  if (typeof raw === 'string') {
    try {
      obj = JSON.parse(raw)
    } catch {
      return null
    }
  }
  if (!isRecord(obj)) return null

  const result: AiRawAnalysis = {
    queries: strArray(obj['queries']),
    executive_summary: section(obj['executive_summary'], (r) => ({
      essence: str(r['essence']),
      key_conclusion: str(r['key_conclusion']),
      confidence_level: str(r['confidence_level']),
    })),
    macro_analysis: section(obj['macro_analysis'], (r) => ({
      applied_frameworks: strArray(r['applied_frameworks']),
      macro_indicators_impact: str(r['macro_indicators_impact']),
      transmission_mechanisms: str(r['transmission_mechanisms']),
    })),
    technical_analysis: section(obj['technical_analysis'], (r) => ({
      scenarios: str(r['scenarios']),
      key_levels: str(r['key_levels']),
      risk_management: str(r['risk_management']),
      volume_analysis: str(r['volume_analysis']),
      usd_rub_specifics: str(r['usd_rub_specifics']),
      volatility_regime: str(r['volatility_regime']),
      indicators_behavior: str(r['indicators_behavior']),
      intermarket_analysis: str(r['intermarket_analysis']),
      price_pattern_impact: str(r['price_pattern_impact']),
      operational_checklist: str(r['operational_checklist']),
      applicable_instruments: str(r['applicable_instruments']),
      trading_recommendations: str(r['trading_recommendations']),
    })),
    behavioral_analysis: section(obj['behavioral_analysis'], (r) => ({
      applied_models: strArray(r['applied_models']),
      cognitive_biases: strArray(r['cognitive_biases']),
      market_reaction_type: str(r['market_reaction_type']),
      overshooting_probability: str(r['overshooting_probability']),
    })),
    fundamental_analysis: section(obj['fundamental_analysis'], (r) => ({
      reasoning: str(r['reasoning']),
      financial_impact: str(r['financial_impact']),
      affected_entities: strArray(r['affected_entities']),
      applied_methodologies: strArray(r['applied_methodologies']),
      fair_value_assessment: str(r['fair_value_assessment']),
    })),
    synergy_insights: section(obj['synergy_insights'], (r) => ({
      blind_spots: strArray(r['blind_spots']),
      signal_vs_noise: str(r['signal_vs_noise']),
      macro_trend_links: strArray(r['macro_trend_links']),
      secondary_effects: strArray(r['secondary_effects']),
      suggested_additional_data: strArray(r['suggested_additional_data']),
    })),
    practical_conclusions: section(obj['practical_conclusions'], (r) => ({
      key_takeaways: strArray(r['key_takeaways']),
      events_to_watch: strArray(r['events_to_watch']),
      revision_triggers: strArray(r['revision_triggers']),
    })),
    quantitative_analysis_and_risks: section(obj['quantitative_analysis_and_risks'], (r) => ({
      key_risks: strArray(r['key_risks']),
      applied_models: strArray(r['applied_models']),
      volatility_impact: str(r['volatility_impact']),
      correlation_changes: str(r['correlation_changes']),
    })),
    sector_and_competitive_analysis: section(obj['sector_and_competitive_analysis'], (r) => ({
      losers: strArray(r['losers']),
      beneficiaries: strArray(r['beneficiaries']),
      competitive_impact: str(r['competitive_impact']),
      supply_chain_impact: str(r['supply_chain_impact']),
    })),
  }

  // Если ни один блок не заполнен — считаем ответ непригодным для карточки
  const hasAny = Object.values(result).some((v) => v !== undefined && v !== null)
  return hasAny ? result : null
}

/* ======================= Словари подписей и бейджей ======================== */

export type BadgeTone = 'gold' | 'neutral' | 'dark'

export interface Badge {
  label: string
  tone: BadgeTone
}

const CONFIDENCE_LABELS: Record<string, Badge> = {
  high: { label: 'Уверенность: высокая', tone: 'gold' },
  medium: { label: 'Уверенность: средняя', tone: 'neutral' },
  low: { label: 'Уверенность: низкая', tone: 'dark' },
}

const REACTION_LABELS: Record<string, Badge> = {
  emotional: { label: 'Реакция рынка: эмоциональная', tone: 'gold' },
  rational: { label: 'Реакция рынка: рациональная', tone: 'neutral' },
  mixed: { label: 'Реакция рынка: смешанная', tone: 'neutral' },
}

const PROBABILITY_LABELS: Record<string, Badge> = {
  high: { label: 'Перегрев цены: высокий', tone: 'gold' },
  medium: { label: 'Перегрев цены: средний', tone: 'neutral' },
  low: { label: 'Перегрев цены: низкий', tone: 'dark' },
}

const FAIR_VALUE_LABELS: Record<string, Badge> = {
  decline: { label: 'Справедливая стоимость: снижение', tone: 'dark' },
  growth: { label: 'Справедливая стоимость: рост', tone: 'gold' },
  up: { label: 'Справедливая стоимость: рост', tone: 'gold' },
  upgrade: { label: 'Справедливая стоимость: рост', tone: 'gold' },
  increase: { label: 'Справедливая стоимость: рост', tone: 'gold' },
  neutral: { label: 'Справедливая стоимость: без изменений', tone: 'neutral' },
  unchanged: { label: 'Справедливая стоимость: без изменений', tone: 'neutral' },
  hold: { label: 'Справедливая стоимость: без изменений', tone: 'neutral' },
}

function badgeFor(dict: Record<string, Badge>, value?: string): Badge | null {
  if (!value) return null
  return dict[value.trim().toLowerCase()] ?? null
}

export const confidenceBadge = (v?: string): Badge | null => badgeFor(CONFIDENCE_LABELS, v)
export const reactionBadge = (v?: string): Badge | null => badgeFor(REACTION_LABELS, v)
export const overshootBadge = (v?: string): Badge | null => badgeFor(PROBABILITY_LABELS, v)
export const fairValueBadge = (v?: string): Badge | null => badgeFor(FAIR_VALUE_LABELS, v)

/** Произвольное enum-значение → нейтральный бейдж с заглавной русской буквой. */
export function genericBadge(value?: string): Badge | null {
  if (!value) return null
  const normalized = value.trim()
  if (normalized === '') return null
  return { label: normalized.charAt(0).toUpperCase() + normalized.slice(1).toLowerCase(), tone: 'neutral' }
}
