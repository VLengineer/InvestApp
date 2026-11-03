<script setup lang="ts">
/**
 * PriceChart.vue — график цены на TradingView Lightweight Charts:
 *  - свечи (open/high/low/close по candle_time);
 *  - маркеры новостей: маленький золотой круг (--color-gold) там, где у записи
 *    непустой ai_text_summary; клик по маркеру → событие marker-click(newsId);
 *  - real-time: метод upsert(item) добавляет/перезаписывает свечу без перезагрузки.
 * Императивная работа с chart API (данные приходят потоком), поэтому
 * watch только на полный набор истории.
 *
 * Синхронизация с осцилляторами (Задача 3): компонент создаёт общий
 * «барабан времени» useChartSync, отдаёт его в Dashboard → OscillatorCharts,
 * транслирует изменения own time-scale (зум/скролл) в общее окно и
 * подсвечивает кроссхэйр по времени из осцилляторов (setCrosshairPosition).
 */
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import {
  createChart,
  ColorType,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
  type MouseEventParams,
} from 'lightweight-charts'
import type { MarketDataItem } from '../types/market'
import { candleTime, hasAiSummary, toCandles, upsertByTime, type CandlePoint } from '../utils/chartData'
import { useChartSync, type ChartSync } from '../composables/useChartSync'

const props = defineProps<{
  /** История записей для конкретного FIGI (до 500). */
  data: MarketDataItem[]
}>()

const emit = defineEmits<{
  /** Клик по маркеру новости: id записи (для GET /api/market/news/{id}). */
  (e: 'marker-click', newsId: string): void
  /** Общий барабан времени готов — Dashboard пробрасывает его в осцилляторы. */
  (e: 'sync-ready', sync: ChartSync): void
}>()

/** Собственный барабан синхронизации (Dashboard заберёт его через sync-ready). */
const sync = useChartSync()

const containerEl = ref<HTMLElement | null>(null)
const chart = shallowRef<IChartApi | null>(null)
const candleSeries = shallowRef<ISeriesApi<'Candlestick'> | null>(null)

// Актуальные свечи и маркеры живут в refs вне реактивности ради производительности
const candles = shallowRef<CandlePoint[]>([])
interface NewsMarker extends SeriesMarker<Time> {
  newsId: string
}
const markers = shallowRef<NewsMarker[]>([])

/**
 * Палитра графика берётся из CSS-переменных tokens.css (Modern Platinum):
 * изменив --color-gold в токенах, золотой акцент поменяется и на графике.
 */
function cssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

let GOLD = '#B8935A'          // --color-gold
let PLATINUM = '#A8A8A8'      // --color-platinum-dark
let INK = '#111111'           // --color-ink
let BG = '#FFFFFF'            // --color-bg-elevated
let LINE = '#D8D8D8'          // --color-platinum
let GRID = '#F2F2F0'          // --color-platinum-soft
let TEXT_SECONDARY = '#666666'// --color-grey

function syncPaletteFromTokens() {
  GOLD = cssVar('--color-gold', GOLD)
  PLATINUM = cssVar('--color-platinum-dark', PLATINUM)
  INK = cssVar('--color-ink', INK)
  BG = cssVar('--color-bg-elevated', BG)
  LINE = cssVar('--color-platinum', LINE)
  GRID = cssVar('--color-platinum-soft', GRID)
  TEXT_SECONDARY = cssVar('--color-grey', TEXT_SECONDARY)
}

function buildMarkers(items: MarketDataItem[]): NewsMarker[] {
  const out: NewsMarker[] = []
  for (const item of items) {
    if (!hasAiSummary(item)) continue
    const time = candleTime(item)
    if (time === null) continue
    out.push({
      time: time as Time,
      position: 'aboveBar',
      color: GOLD,
      shape: 'circle',
      text: 'Новость',
      newsId: item.id,
    })
  }
  // Lightweight Charts требует сортировки маркеров по времени
  return out.sort((a, b) => (a.time as number) - (b.time as number))
}

function applyMarkers() {
  candleSeries.value?.setMarkers(markers.value as SeriesMarker<Time>[])
}

function renderHistory(items: MarketDataItem[]) {
  if (!candleSeries.value) return
  candles.value = toCandles(items)
  candleSeries.value.setData(candles.value.map((c) => ({ ...c, time: c.time as Time })))
  markers.value = buildMarkers(items)
  applyMarkers()
  if (candles.value.length > 0) {
    chart.value?.timeScale().fitContent()
  }
}

/**
 * Real-time: добавить/обновить одну свечу и (при наличии ИИ-аналитики) маркер.
 * Вызывается из Dashboard.vue при получении new_data по WebSocket.
 */
function upsert(item: MarketDataItem) {
  const time = candleTime(item)
  if (time === null || !candleSeries.value) return
  const point: CandlePoint = {
    time,
    open: item.open_price,
    high: item.high_price,
    low: item.low_price,
    close: item.close_price,
  }
  candles.value = upsertByTime(candles.value, point)
  candleSeries.value.update({ ...point, time: time as Time })
  if (hasAiSummary(item)) {
    // замена маркера с тем же time (свеча могла обновиться)
    const marker: NewsMarker = {
      time: time as Time,
      position: 'aboveBar',
      color: GOLD,
      shape: 'circle',
      text: 'Новость',
      newsId: item.id,
    }
    markers.value = [
      ...markers.value.filter((m) => m.time !== time),
      marker,
    ].sort((a, b) => (a.time as number) - (b.time as number))
    applyMarkers()
  }
}

defineExpose({ upsert, sync, setOscillatorCrosshair })

function onChartClick(param: MouseEventParams) {
  if (!param.time) return
  // Ищем маркер новости в точке клика (по времени свечи)
  const marker = markers.value.find((m) => m.time === param.time)
  if (marker) emit('marker-click', marker.newsId)
}

/* ------------------ Синхронизация окна с осцилляторами -------------------- */

/** true, пока окно меняется программно (защита от эха событий подписки). */
let applyingExternal = false

/** Последнее окно, опубликованное этим графиком (фильтр собственного эха). */
let lastPublished: [number, number] = [-1, -1]

/** Пересчёт видимого окна time-scale → индексы барабана и в sync. */
function publishWindowFromTimeScale() {
  const c = chart.value
  if (!c || sync.drum.value.length === 0) return
  const ts = c.timeScale()
  const range = ts.getVisibleRange()
  if (!range) return
  const from = typeof range.from === 'number' ? range.from : null
  const to = typeof range.to === 'number' ? range.to : null
  if (from === null || to === null) return
  const drum = sync.drum.value
  let s = drum.findIndex((t) => t >= from)
  if (s < 0) s = 0
  let e = drum.findIndex((t) => t >= to)
  if (e < 0) e = drum.length
  // Не публикуем «краевые» значения по умолчанию — иначе каждое событие
  // подписки будет бесконечно гонять эхо окно↔time-scale.
  if (s === 0 && e === drum.length) return
  lastPublished = [s, e]
  sync.setWindow(s, e)
}

/** Применить окно из sync к time-scale (когда источник — осциллятор). */
function applyWindowToTimeScale(start: number, end: number) {
  const c = chart.value
  const drum = sync.drum.value
  if (!c || drum.length === 0) return
  const from = drum[Math.min(start, drum.length - 1)]
  const to = drum[Math.min(Math.max(end - 1, start), drum.length - 1)]
  applyingExternal = true
  c.timeScale().setVisibleRange({ from: from as Time, to: to as Time })
  requestAnimationFrame(() => { applyingExternal = false })
}

/** Кроссхэйр от осцилляторов: подсветить точку на свечном графике.
 *  setCrosshairPosition/clearCrosshairPosition есть в runtime Lightweight
 *  Charts 4, но отсутствуют в типах ISeriesApi — узкий адаптер с проверкой. */
interface CrosshairPositionApi {
  setCrosshairPosition?: (price: number, time: Time) => void
  clearCrosshairPosition?: () => void
}

function setOscillatorCrosshair(time: number | null) {
  const series = candleSeries.value as (ISeriesApi<'Candlestick'> & CrosshairPositionApi) | null
  if (!series) return
  if (time === null) {
    series.clearCrosshairPosition?.()
    return
  }
  const candle = candles.value.find((cnd) => cnd.time === time) ?? candles.value[candles.value.length - 1]
  if (!candle) return
  series.setCrosshairPosition?.(candle.close, candle.time as Time)
}

let resizeObserver: ResizeObserver | null = null
let windowUnsub: (() => void) | null = null

onMounted(() => {
  const el = containerEl.value
  if (!el) return
  syncPaletteFromTokens()
  const c = createChart(el, {
    width: el.clientWidth,
    height: 420,
    layout: {
      background: { type: ColorType.Solid, color: BG },
      textColor: TEXT_SECONDARY,
      fontFamily: "'Inter', -apple-system, sans-serif",
    },
    grid: {
      vertLines: { color: GRID },
      horzLines: { color: GRID },
    },
    rightPriceScale: { borderColor: LINE },
    timeScale: { borderColor: LINE, timeVisible: true, secondsVisible: false },
    crosshair: { mode: CrosshairMode.Normal },
    handleScroll: { mouseWheel: true, pressedMouseMove: true },
    handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
  })
  chart.value = c

  const series = c.addCandlestickSeries({
    upColor: GOLD,           // растущая свеча — золото
    downColor: PLATINUM,     // падающая свеча — платина
    borderUpColor: GOLD,
    borderDownColor: PLATINUM,
    wickUpColor: GOLD,
    wickDownColor: PLATINUM,
  })
  candleSeries.value = series

  c.subscribeClick(onChartClick)

  // Зум/скролл свечного графика → общее окно → осцилляторы
  c.timeScale().subscribeVisibleLogicalRangeChange(() => {
    if (applyingExternal) return
    publishWindowFromTimeScale()
  })

  // Окно из осцилляторов → time-scale этого графика (своё эхо не применяем)
  windowUnsub = sync.onWindowChange((s, e) => {
    if (lastPublished[0] === s && lastPublished[1] === e) return
    applyWindowToTimeScale(s, e)
  })

  // Отдаём общий барабан наружу (Dashboard → OscillatorCharts)
  emit('sync-ready', sync)

  // Ресайз без лишних анимаций — только пересчёт размеров
  resizeObserver = new ResizeObserver(() => {
    if (containerEl.value) c.applyOptions({ width: containerEl.value.clientWidth })
  })
  resizeObserver.observe(el)

  renderHistory(props.data)
})

onBeforeUnmount(() => {
  windowUnsub?.()
  resizeObserver?.disconnect()
  chart.value?.remove()
  chart.value = null
  candleSeries.value = null
})

watch(
  () => props.data,
  (items) => {
    // Смена FIGI / полная перезагрузка истории — перерисовываем всё
    if (chart.value) renderHistory(items)
  },
)
</script>

<template>
  <div class="price-chart card pl-card">
    <div class="chart-head">
      <h3 class="chart-title">График цены</h3>
      <span class="chart-hint">Золотые маркеры — новости с ИИ-аналитикой (клик — подробности)</span>
    </div>
    <div ref="containerEl" class="chart-body" />
  </div>
</template>

<style scoped>
/* Flat-карточка Modern Platinum: тонкая платиновая рамка, радиус 2px,
   без тени в покое. Только токены из tokens.css. */
.card {
  padding: var(--space-md);
}

.chart-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-sm);
  margin-bottom: var(--space-sm);
}

.chart-title {
  margin: 0;
  font-size: var(--fs-body);
  font-weight: var(--fw-regular);
  letter-spacing: var(--ls-tight);
  color: var(--color-ink);
}

.chart-hint {
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  color: var(--color-grey-light);
}

.chart-body {
  width: 100%;
}

@media (max-width: 1023px) {
  .chart-head {
    flex-direction: column;
    gap: var(--space-xs);
  }
}
</style>
