<script setup lang="ts">
/**
 * PriceChart.vue — график цены на TradingView Lightweight Charts:
 *  - свечи (open/high/low/close по candle_time);
 *  - маркеры новостей: маленький золотой круг (#D4AF37) там, где у записи
 *    непустой ai_text_summary; клик по маркеру → событие marker-click(newsId);
 *  - real-time: метод upsert(item) добавляет/перезаписывает свечу без перезагрузки.
 * Императивная работа с chart API (данные приходят потоком), поэтому
 * watch только на полный набор истории.
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

const props = defineProps<{
  /** История записей для конкретного FIGI (до 500). */
  data: MarketDataItem[]
}>()

const emit = defineEmits<{
  /** Клик по маркеру новости: id записи (для GET /api/market/news/{id}). */
  (e: 'marker-click', newsId: string): void
}>()

const containerEl = ref<HTMLElement | null>(null)
const chart = shallowRef<IChartApi | null>(null)
const candleSeries = shallowRef<ISeriesApi<'Candlestick'> | null>(null)

// Актуальные свечи и маркеры живут в refs вне реактивности ради производительности
const candles = shallowRef<CandlePoint[]>([])
interface NewsMarker extends SeriesMarker<Time> {
  newsId: string
}
const markers = shallowRef<NewsMarker[]>([])

/** Цвета брендбука для графика. */
const GOLD = '#D4AF37'
const TEXT_SECONDARY = '#6B6B6B'

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

defineExpose({ upsert })

function onChartClick(param: MouseEventParams) {
  if (!param.time) return
  // Ищем маркер новости в точке клика (по времени свечи)
  const marker = markers.value.find((m) => m.time === param.time)
  if (marker) emit('marker-click', marker.newsId)
}

let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  const el = containerEl.value
  if (!el) return
  const c = createChart(el, {
    width: el.clientWidth,
    height: 420,
    layout: {
      background: { type: ColorType.Solid, color: '#FFFFFF' },
      textColor: TEXT_SECONDARY,
      fontFamily: "'Segoe UI', system-ui, sans-serif",
    },
    grid: {
      vertLines: { color: '#F5F5F4' },
      horzLines: { color: '#F5F5F4' },
    },
    rightPriceScale: { borderColor: '#E5E4E2' },
    timeScale: { borderColor: '#E5E4E2', timeVisible: true, secondsVisible: false },
    crosshair: { mode: CrosshairMode.Normal },
    handleScroll: { mouseWheel: true, pressedMouseMove: true },
    handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
  })
  chart.value = c

  const series = c.addCandlestickSeries({
    upColor: '#A8871C',      // растущая свеча — тёмное золото
    downColor: '#B8B7B5',    // падающая свеча — платина
    borderUpColor: '#A8871C',
    borderDownColor: '#B8B7B5',
    wickUpColor: '#A8871C',
    wickDownColor: '#B8B7B5',
  })
  candleSeries.value = series

  c.subscribeClick(onChartClick)

  // Ресайз без лишних анимаций — только пересчёт размеров
  resizeObserver = new ResizeObserver(() => {
    if (containerEl.value) c.applyOptions({ width: containerEl.value.clientWidth })
  })
  resizeObserver.observe(el)

  renderHistory(props.data)
})

onBeforeUnmount(() => {
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
  <div class="price-chart card">
    <div class="chart-head">
      <h3 class="chart-title">График цены</h3>
      <span class="chart-hint">Золотые маркеры — новости с ИИ-аналитикой (клик — подробности)</span>
    </div>
    <div ref="containerEl" class="chart-body" />
  </div>
</template>

<style scoped>
.card {
  background: #ffffff;
  border: 1px solid var(--color-platinum, #e5e4e2);
  border-radius: 8px;
  padding: 16px;
}

.chart-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.chart-title {
  margin: 0;
  font-size: 15px;
  font-weight: 400;
  letter-spacing: 0.03em;
  color: var(--color-text-primary, #1a1a1a);
}

.chart-hint {
  font-size: 12px;
  font-weight: 300;
  color: var(--color-text-secondary, #6b6b6b);
}

.chart-body {
  width: 100%;
}
</style>
