<script setup lang="ts">
/**
 * OscillatorCharts.vue — осцилляторы на ECharts (по ТЗ):
 * RSI_14, MACD (+ signal + гистограмма), Stochastic (K, D), CCI_20,
 * Williams %R, ROC_12, MFI_14, ADX_14.
 * Каждый осциллятор — отдельный график высотой 150px; цветовая схема:
 * золотой для основных линий, платиновый для вспомогательных.
 * Real-time: при изменении массива data (append/upsert из Dashboard)
 * графики обновляются без перезагрузки страницы.
 *
 * Интерактивность (Задача 3):
 *  * зум колесом/пинчем и панорамирование drag'ом через общий «барабан
 *    времени» useChartSync — окно синхронизировано с PriceChart (свечи);
 *  * crosshair с tooltip'ом точных значений + рассылка перекрестия между
 *    всеми графиками группы (createCrosshairHub);
 *  * кнопка «На весь экран» (useFullscreen) — разворот блока осцилляторов.
 */
import { onBeforeUnmount, onMounted, shallowRef, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsOption } from 'echarts'
import type { MarketDataItem } from '../types/market'
import { candleTime, timeLabels } from '../utils/chartData'
import {
  attachWheelZoomScroll,
  createCrosshairHub,
  useChartSync,
  type ChartSync,
  type CrosshairHub,
} from '../composables/useChartSync'
import { useFullscreen } from '../composables/useFullscreen'

// Регистрируем только нужные модули ECharts — меньше бандл, быстрее загрузка
echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])

const props = defineProps<{
  data: MarketDataItem[]
  /** Общий барабан времени из Dashboard.vue (синхронизация со свечным графиком). */
  sync?: ChartSync | null
}>()

const emit = defineEmits<{
  /** Метка времени свечи под курсором (для синхронного кроссхэйра со свечами). */
  (e: 'crosshair-time', time: number | null): void
}>()

const rootEl = shallowRef<HTMLElement | null>(null)
const { isFullscreen, toggle: toggleFullscreen } = useFullscreen(rootEl)

/**
 * Палитра графика берётся из CSS-переменных tokens.css (Modern Platinum):
 * изменив --color-gold в токенах, золотой акцент поменяется и здесь.
 */
function cssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

let GOLD = '#B8935A'            // --color-gold
let PLATINUM = '#A8A8A8'        // --color-platinum-dark
let INK_SOFT = '#333333'        // --color-ink-soft
let LINE = '#D8D8D8'            // --color-platinum
let GRID = '#F2F2F0'            // --color-platinum-soft
let TEXT_SECONDARY = '#666666'  // --color-grey

function syncPaletteFromTokens() {
  GOLD = cssVar('--color-gold', GOLD)
  PLATINUM = cssVar('--color-platinum-dark', PLATINUM)
  INK_SOFT = cssVar('--color-ink-soft', INK_SOFT)
  LINE = cssVar('--color-platinum', LINE)
  GRID = cssVar('--color-platinum-soft', GRID)
  TEXT_SECONDARY = cssVar('--color-grey', TEXT_SECONDARY)
}

interface SeriesDef {
  name: string
  /** Поле записи-источник; для спецсерии 'macd_hist' считается как macd − macd_signal. */
  field: keyof MarketDataItem | 'macd_hist'
  color: string
  type: 'line' | 'bar'
}

interface ChartDef {
  key: string
  title: string
  series: SeriesDef[]
}

const CHART_DEFS: ChartDef[] = [
  { key: 'rsi_14', title: 'RSI_14', series: [{ name: 'RSI', field: 'rsi_14', color: GOLD, type: 'line' }] },
  {
    key: 'macd',
    title: 'MACD',
    series: [
      { name: 'MACD', field: 'macd', color: GOLD, type: 'line' },
      { name: 'Signal', field: 'macd_signal', color: PLATINUM, type: 'line' },
      { name: 'Гистограмма', field: 'macd_hist', color: GOLD, type: 'bar' },
    ],
  },
  {
    key: 'stoch',
    title: 'Stochastic',
    series: [
      { name: '%K', field: 'stoch_k', color: GOLD, type: 'line' },
      { name: '%D', field: 'stoch_d', color: PLATINUM, type: 'line' },
    ],
  },
  { key: 'cci_20', title: 'CCI_20', series: [{ name: 'CCI', field: 'cci_20', color: GOLD, type: 'line' }] },
  { key: 'williams_r', title: 'Williams %R', series: [{ name: '%R', field: 'williams_r', color: GOLD, type: 'line' }] },
  { key: 'roc_12', title: 'ROC_12', series: [{ name: 'ROC', field: 'roc_12', color: GOLD, type: 'line' }] },
  { key: 'mfi_14', title: 'MFI_14', series: [{ name: 'MFI', field: 'mfi_14', color: GOLD, type: 'line' }] },
  { key: 'adx_14', title: 'ADX_14', series: [{ name: 'ADX', field: 'adx_14', color: GOLD, type: 'line' }] },
]

type EChartInstance = ReturnType<typeof echarts.init>

const wrapEl = shallowRef<HTMLElement | null>(null)
const instances = new Map<string, EChartInstance>()
const resizeHandlers: Array<() => void> = []

/** Числовое значение поля или null (в ECharts null разрывает линию). */
function num(item: MarketDataItem, field: keyof MarketDataItem): number | null {
  const v = item[field]
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}

/** Значение серии: обычное поле либо гистограмма MACD (macd − signal). */
function seriesValue(def: SeriesDef, item: MarketDataItem): number | null {
  if (def.field === 'macd_hist') {
    const m = num(item, 'macd')
    const s = num(item, 'macd_signal')
    return m !== null && s !== null ? +(m - s).toFixed(6) : null
  }
  return num(item, def.field)
}

function buildOption(def: ChartDef, items: MarketDataItem[]): EChartsOption {
  // Метки времени: одна на запись (дубли времен допустимы — category axis)
  const times = items.map((it) => candleTime(it)).filter((t): t is number => t !== null)
  const labels = timeLabels(times)

  return {
    animation: false, // «не грузить ПК лишними анимациями»
    grid: { left: 48, right: 12, top: 26, bottom: 20 },
    // Crosshair + tooltip точных значений (Задача 3)
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'cross',
        label: { backgroundColor: INK_SOFT, fontSize: 10 },
        crossStyle: { color: PLATINUM },
      },
      textStyle: { fontSize: 11 },
      formatter: ((params: unknown) => formatTooltip(def, items, params)) as never,
    },
    // Программный зум окном useChartSync (startValue/endValue задаются извне)
    dataZoom: [
      { type: 'hidden', xAxisIndex: 0, startValue: 0, endValue: Math.max(1, labels.length - 1) },
    ],
    xAxis: {
      type: 'category',
      data: labels,
      boundaryGap: def.series.some((s) => s.type === 'bar'),
      axisLine: { lineStyle: { color: LINE } },
      axisTick: { show: false },
      axisLabel: { color: TEXT_SECONDARY, fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      scale: true,
      splitLine: { lineStyle: { color: GRID } },
      axisLabel: { color: TEXT_SECONDARY, fontSize: 10 },
    },
    title: {
      text: def.title,
      left: 4,
      top: 2,
      textStyle: { fontSize: 12, fontWeight: 300 as never, color: TEXT_SECONDARY },
    },
    series: def.series.map((s) => {
      const data = items.map((it) => seriesValue(s, it))
      if (s.type === 'bar') {
        return {
          name: s.name,
          type: 'bar' as const,
          data,
          itemStyle: { color: `${GOLD}59` }, // золото, полупрозрачное (hex alpha)
          barWidth: '60%',
        }
      }
      return {
        name: s.name,
        type: 'line' as const,
        data,
        showSymbol: false,
        lineStyle: { color: s.color, width: 1.2 },
        itemStyle: { color: s.color },
      }
    }),
  }
}

/** Точные значения в tooltip: метка времени + серия с числом. */
interface TooltipParam {
  axisIndex?: number
  axisValue?: string | number
  seriesName?: string
  value?: number | string | null
  color?: string
}

function formatTooltip(def: ChartDef, items: MarketDataItem[], params: unknown): string {
  const list = Array.isArray(params) ? (params as TooltipParam[]) : [params as TooltipParam]
  const idx = list[0]?.axisIndex
  const time = typeof idx === 'number' ? candleTime(items[idx] ?? ({} as MarketDataItem)) : null
  const head = time !== null && time !== undefined
    ? new Date(time * 1000).toLocaleString('ru-RU')
    : escapeHtml(String(list[0]?.axisValue ?? def.title))
  const rows = list
    .filter((p) => p && p.value !== null && p.value !== undefined && p.value !== '')
    .map((p) => {
      const v = typeof p.value === 'number' ? p.value.toFixed(4) : escapeHtml(String(p.value))
      return `<div>${escapeHtml(p.seriesName ?? '')}: <b>${v}</b></div>`
    })
  return `<div style="min-width:120px"><b>${head}</b>${rows.join('')}</div>`
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (ch) => `&#${ch.charCodeAt(0)};`)
}

/* ------------------ Синхронизация, кроссхэйр, зум/скролл ------------------- */

/** Локальный барабан на случай, если Dashboard не передал общий sync. */
const localSync = useChartSync()
const activeSync = (): ChartSync => props.sync ?? localSync

const hub: CrosshairHub = createCrosshairHub()
const cleanups: Array<() => void> = []
let windowUnsub: (() => void) | null = null

/** Применить текущее окно синхронизации ко всем инстансам. */
function applyWindow(start: number, end: number) {
  for (const inst of instances.values()) {
    inst.setOption({
      dataZoom: [{ type: 'hidden', xAxisIndex: 0, startValue: start, endValue: Math.max(start + 1, end - 1) }],
    })
  }
}

/** Обновить барабан при перерисовке истории (labels соответствуют items). */
function updateDrum(items: MarketDataItem[]) {
  const sync = activeSync()
  const times = items.map((it) => candleTime(it)).filter((t): t is number => t !== null)
  if (times.length === 0) return
  // Если данные совпадают с барабаном — не сбрасываем текущий зум пользователя
  const drum = sync.drum.value
  if (drum.length === times.length && drum[0] === times[0] && drum[drum.length - 1] === times[times.length - 1]) {
    return
  }
  sync.setDrum(times)
}

function bindInteractions(el: HTMLElement, inst: ReturnType<typeof echarts.init>) {
  const offWheel = attachWheelZoomScroll(el, activeSync())
  const onMouseEvent = (payload: { dataIndex?: number; axesInfo?: unknown[] }) => {
    const hasPoint = (payload.axesInfo?.length ?? 0) > 0 || payload.dataIndex !== undefined
    if (!hasPoint) {
      emit('crosshair-time', null)
      return
    }
    const items = props.data
    const idx = typeof payload.dataIndex === 'number' ? payload.dataIndex : -1
    const t = idx >= 0 ? candleTime(items[idx] ?? ({} as MarketDataItem)) : null
    emit('crosshair-time', t ?? null)
  }
  inst.on('updateAxisPointer', onMouseEvent as never)
  cleanups.push(() => inst.off('updateAxisPointer', onMouseEvent as never))
  cleanups.push(offWheel)
}

function renderAll(items: MarketDataItem[]) {
  for (const def of CHART_DEFS) {
    const inst = instances.get(def.key)
    if (!inst) continue
    inst.setOption(buildOption(def, items), { notMerge: true })
  }
  updateDrum(items)
  const sync = activeSync()
  applyWindow(sync.startIdx.value, sync.endIdx.value)
}

onMounted(() => {
  syncPaletteFromTokens()
  const wrap = wrapEl.value
  if (!wrap) return
  for (const def of CHART_DEFS) {
    const el = wrap.querySelector<HTMLElement>(`[data-chart="${def.key}"]`)
    if (!el) continue
    const inst = echarts.init(el, undefined, { renderer: 'canvas' })
    instances.set(def.key, inst)
    hub.register(inst)
    const onResize = () => inst.resize()
    window.addEventListener('resize', onResize)
    resizeHandlers.push(onResize)
    bindInteractions(el, inst)
  }
  renderAll(props.data)

  // Подписка на общее окно (зум/скролл со свечного графика или другого осциллятора)
  windowUnsub = activeSync().onWindowChange(applyWindow)
})

onBeforeUnmount(() => {
  if (windowUnsub) windowUnsub()
  for (const fn of cleanups) fn()
  cleanups.length = 0
  for (const fn of resizeHandlers) window.removeEventListener('resize', fn)
  resizeHandlers.length = 0
  for (const inst of instances.values()) inst.dispose()
  instances.clear()
})

// Обновление при real-time данных и при смене FIGI (массив пересоздаётся в Dashboard)
watch(
  () => props.data,
  (items) => renderAll(items),
)
</script>

<template>
  <div ref="rootEl" class="oscillators card pl-card" :class="{ 'is-fullscreen': isFullscreen }">
    <div class="head">
      <h3 class="block-title">Осцилляторы</h3>
      <div class="tools">
        <button type="button" class="tool-btn" title="Сбросить зум" @click="activeSync().fitAll()">Весь период</button>
        <button
          type="button"
          class="tool-btn"
          :aria-pressed="isFullscreen"
          :title="isFullscreen ? 'Выйти из полноэкранного режима' : 'Раскрыть на весь экран'"
          @click="toggleFullscreen()"
        >{{ isFullscreen ? 'Свернуть' : 'На весь экран' }}</button>
      </div>
    </div>
    <p class="hint">Колесо мыши — зум, перетаскивание — панорамирование; окно синхронизировано с графиком цены.</p>
    <div ref="wrapEl" class="grid">
      <div v-for="def in CHART_DEFS" :key="def.key" class="cell">
        <div :data-chart="def.key" class="chart" />
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Одна flat-карточка «Осцилляторы» с сеткой мини-графиков.
   Только токены из tokens.css. */
.oscillators {
  padding: var(--space-md);
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-sm);
  margin-bottom: var(--space-xs);
}

.block-title {
  margin: 0;
  font-size: var(--fs-body);
  font-weight: var(--fw-regular);
  letter-spacing: var(--ls-tight);
  color: var(--color-ink);
}

.tools {
  display: flex;
  gap: var(--space-xs);
}

.tool-btn {
  padding: 4px 10px;
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  letter-spacing: var(--ls-wide);
  text-transform: uppercase;
  color: var(--color-ink);
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-platinum);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out);
}

.tool-btn:hover {
  border-color: var(--color-gold);
  color: var(--color-gold);
}

.hint {
  margin: 0 0 var(--space-sm);
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  color: var(--color-grey-light);
}

.grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-sm);
}

.cell {
  min-width: 0;
}

.chart {
  width: 100%;
  height: 160px;
}

/* Fullscreen: фон и растягиваем сетку на весь экран, графики выше */
.is-fullscreen {
  background: var(--color-bg-elevated);
  overflow: auto;
  padding: var(--space-lg, 24px);
}

.is-fullscreen .grid {
  grid-template-columns: repeat(2, 1fr);
}

.is-fullscreen .chart {
  height: 300px;
}

/* ---------- Адаптив: на планшете/мобильном — одна колонка ---------- */
@media (max-width: 1023px) {
  .grid {
    grid-template-columns: 1fr;
  }

  .is-fullscreen .grid {
    grid-template-columns: 1fr;
  }
}
</style>
