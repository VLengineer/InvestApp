<script setup lang="ts">
/**
 * OscillatorCharts.vue — осцилляторы на ECharts (по ТЗ):
 * RSI_14, MACD (+ signal + гистограмма), Stochastic (K, D), CCI_20,
 * Williams %R, ROC_12, MFI_14, ADX_14.
 * Каждый осциллятор — отдельный график высотой 150px; цветовая схема:
 * золотой для основных линий, платиновый для вспомогательных.
 * Real-time: при изменении массива data (append/upsert из Dashboard)
 * графики обновляются без перезагрузки страницы.
 */
import { onBeforeUnmount, onMounted, shallowRef, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsOption } from 'echarts'
import type { MarketDataItem } from '../types/market'
import { candleTime, timeLabels } from '../utils/chartData'

// Регистрируем только нужные модули ECharts — меньше бандл, быстрее загрузка
echarts.use([LineChart, BarChart, GridComponent, CanvasRenderer])

const props = defineProps<{ data: MarketDataItem[] }>()

const GOLD = '#D4AF37'
const PLATINUM = '#B8B7B5'
const TEXT_SECONDARY = '#6B6B6B'

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
  const labels = timeLabels(items.map((it) => candleTime(it)).filter((t): t is number => t !== null))

  return {
    animation: false, // «не грузить ПК лишними анимациями»
    grid: { left: 48, right: 12, top: 26, bottom: 20 },
    xAxis: {
      type: 'category',
      data: labels,
      boundaryGap: def.series.some((s) => s.type === 'bar'),
      axisLine: { lineStyle: { color: '#E5E4E2' } },
      axisTick: { show: false },
      axisLabel: { color: TEXT_SECONDARY, fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      scale: true,
      splitLine: { lineStyle: { color: '#F5F5F4' } },
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
          itemStyle: { color: 'rgba(212, 175, 55, 0.35)' }, // золото, полупрозрачное
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

function renderAll(items: MarketDataItem[]) {
  for (const def of CHART_DEFS) {
    const inst = instances.get(def.key)
    if (!inst) continue
    inst.setOption(buildOption(def, items), { notMerge: true })
  }
}

onMounted(() => {
  const wrap = wrapEl.value
  if (!wrap) return
  for (const def of CHART_DEFS) {
    const el = wrap.querySelector<HTMLElement>(`[data-chart="${def.key}"]`)
    if (!el) continue
    const inst = echarts.init(el, undefined, { renderer: 'canvas' })
    instances.set(def.key, inst)
    const onResize = () => inst.resize()
    window.addEventListener('resize', onResize)
    resizeHandlers.push(onResize)
  }
  renderAll(props.data)
})

onBeforeUnmount(() => {
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
  <div ref="wrapEl" class="oscillators card">
    <h3 class="block-title">Осцилляторы</h3>
    <div class="grid">
      <div v-for="def in CHART_DEFS" :key="def.key" class="cell">
        <div :data-chart="def.key" class="chart" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.card {
  background: #ffffff;
  border: 1px solid var(--color-platinum, #e5e4e2);
  border-radius: 8px;
  padding: 16px;
}

.block-title {
  margin: 0 0 12px;
  font-size: 15px;
  font-weight: 400;
  letter-spacing: 0.03em;
  color: var(--color-text-primary, #1a1a1a);
}

.grid {
  display: grid;
  /* Адаптив: от 1280px — 4 колонки, меньше — 2 */
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

@media (min-width: 1280px) {
  .grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

.cell {
  min-width: 0;
}

.chart {
  height: 150px;
  width: 100%;
}
</style>
