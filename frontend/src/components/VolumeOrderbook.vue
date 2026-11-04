<script setup lang="ts">
/**
 * VolumeOrderbook.vue — объёмы (ECharts bar: volume / volume_buy / volume_sell)
 * и стакан (визуализация последних orderbook_asks / orderbook_bids + depth).
 * Real-time: обновляется при изменении массива data из Dashboard.vue.
 */
import { computed, onBeforeUnmount, onMounted, shallowRef, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsOption } from 'echarts'
import type { MarketDataItem } from '../types/market'
import { candleTime, timeLabels } from '../utils/chartData'

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{ data: MarketDataItem[] }>()

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

/* ---------------- График объёмов ---------------- */

const volEl = shallowRef<HTMLElement | null>(null)
let volChart: ReturnType<typeof echarts.init> | null = null

function renderVolumes(items: MarketDataItem[]) {
  if (!volChart) return
  const times: number[] = []
  const total: number[] = []
  const buy: number[] = []
  const sell: number[] = []
  for (const it of items) {
    const t = candleTime(it)
    if (t === null) continue
    times.push(t)
    total.push(it.volume)
    buy.push(it.volume_buy)
    sell.push(it.volume_sell)
  }
  const option: EChartsOption = {
    animation: false,
    grid: { left: 56, right: 12, top: 28, bottom: 20 },
    tooltip: { trigger: 'axis' },
    legend: {
      right: 0,
      top: 0,
      textStyle: { fontSize: 11, color: TEXT_SECONDARY },
      itemWidth: 10,
      itemHeight: 8,
    },
    xAxis: {
      type: 'category',
      data: timeLabels(times),
      axisLine: { lineStyle: { color: LINE } },
      axisTick: { show: false },
      axisLabel: { color: TEXT_SECONDARY, fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: GRID } },
      axisLabel: { color: TEXT_SECONDARY, fontSize: 10 },
    },
    series: [
      { name: 'Volume', type: 'bar', data: total, itemStyle: { color: `${GOLD}73` }, barWidth: '70%' },
      { name: 'Buy', type: 'bar', data: buy, itemStyle: { color: GOLD }, stack: 'bs' },
      { name: 'Sell', type: 'bar', data: sell, itemStyle: { color: PLATINUM }, stack: 'bs' },
    ],
  }
  volChart.setOption(option, { notMerge: true })
}

/* ---------------- Стакан (order book) ---------------- */

/** Последняя запись с непустым стаканом. */
const lastWithBook = computed<MarketDataItem | null>(() => {
  for (let i = props.data.length - 1; i >= 0; i--) {
    const it = props.data[i]
    if (it.orderbook_asks?.length || it.orderbook_bids?.length) return it
  }
  return null
})

const asks = computed(() => (lastWithBook.value?.orderbook_asks ?? []).slice(0, 10))
const bids = computed(() => (lastWithBook.value?.orderbook_bids ?? []).slice(0, 10))

/** Максимальный объём в видимых уровнях — для ширины полос. */
const maxQty = computed(() => {
  let m = 0
  for (const l of [...asks.value, ...bids.value]) m = Math.max(m, l.quantity)
  return m || 1
})

function fmt(n: number): string {
  return n.toLocaleString('ru-RU', { maximumFractionDigits: 2 })
}

/* ---------------- Lifecycle ---------------- */

/**
 * Ресайз через rAF-батчинг: ECharts запрещает resize() во время «main
 * process» (внутреннего update-цикла); прямой вызов из события 'resize'
 * мог попасть в этот момент и ронял ошибку "`resize` should not be called
 * during main process".
 */
let volRaf = 0
let volResizeObserver: ResizeObserver | null = null

function scheduleVolResize() {
  if (volRaf) return
  volRaf = requestAnimationFrame(() => {
    volRaf = 0
    Promise.resolve().then(() => {
      if (volChart && !volChart.isDisposed()) volChart.resize({ animation: { duration: 0 } })
    })
  })
}

onMounted(() => {
  syncPaletteFromTokens()
  if (volEl.value) {
    volChart = echarts.init(volEl.value, undefined, { renderer: 'canvas' })
    renderVolumes(props.data)
    window.addEventListener('resize', scheduleVolResize)
    // ResizeObserver: карточка меняет высоту вместе с grid-строкой Dashboard
    // (и при переносе в одну колонку), а не только при resize окна.
    volResizeObserver = new ResizeObserver(scheduleVolResize)
    volResizeObserver.observe(volEl.value)
  }
})

onBeforeUnmount(() => {
  if (volRaf) cancelAnimationFrame(volRaf)
  volRaf = 0
  volResizeObserver?.disconnect()
  volResizeObserver = null
  window.removeEventListener('resize', scheduleVolResize)
  volChart?.dispose()
  volChart = null
})

watch(() => props.data, (items) => renderVolumes(items))
</script>

<template>
  <div class="volumes-row">
    <!-- Объёмы -->
    <section class="card pl-card">
      <h3 class="block-title">Объёмы</h3>
      <div ref="volEl" class="vol-chart" />
    </section>

    <!-- Стакан -->
    <section class="card pl-card book-card">
      <h3 class="block-title">
        Стакан
        <span v-if="lastWithBook?.depth != null" class="depth-badge">
          глубина {{ lastWithBook.depth }}
        </span>
      </h3>

      <div v-if="!lastWithBook" class="book-empty">Нет данных стакана</div>

      <div v-else class="book">
        <div class="book-col">
          <div class="col-head ask-head">Ask</div>
          <div v-for="lvl in [...asks].reverse()" :key="'a' + lvl.position" class="level">
            <span class="qty-bar ask-bar" :style="{ width: (lvl.quantity / maxQty) * 100 + '%' }" />
            <span class="price">{{ fmt(lvl.price) }}</span>
            <span class="qty">{{ fmt(lvl.quantity) }}</span>
          </div>
        </div>
        <div class="divider" />
        <div class="book-col">
          <div class="col-head bid-head">Bid</div>
          <div v-for="lvl in bids" :key="'b' + lvl.position" class="level">
            <span class="qty-bar bid-bar" :style="{ width: (lvl.quantity / maxQty) * 100 + '%' }" />
            <span class="price">{{ fmt(lvl.price) }}</span>
            <span class="qty">{{ fmt(lvl.quantity) }}</span>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
/* Двухколоночная сетка карточек (объёмы | стакан). Flat, только токены.
   height:100% — карточки растягиваются на всю высоту секции Dashboard
   (500px), график объёмов занимает остаток через flex. */
.volumes-row {
  display: grid;
  grid-template-columns: 3fr 2fr;
  gap: var(--space-sm);
  height: 100%;
}

.card {
  padding: var(--space-md);
}

/* Карточки растягиваются на всю высоту grid-строки, график объёмов
   занимает остальное место — height не «прыгает» и canvas корректно
   пересчитывается через ResizeObserver. */
.volumes-row > .card {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.block-title {
  display: flex;
  align-items: baseline;
  gap: var(--space-xs);
  margin: 0 0 var(--space-sm);
  font-size: var(--fs-body);
  font-weight: var(--fw-regular);
  letter-spacing: var(--ls-tight);
  color: var(--color-ink);
}

.depth-badge {
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  letter-spacing: var(--ls-tight);
  color: var(--color-gold);
}

.vol-chart {
  width: 100%;
  flex: 1;
  min-height: 180px;
}

.book-empty {
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  color: var(--color-grey-light);
}

.book {
  display: flex;
  gap: var(--space-xs);
}

.book-col {
  flex: 1;
  min-width: 0;
}

.col-head {
  display: block;
  font-size: var(--fs-micro);
  font-weight: var(--fw-medium);
  letter-spacing: var(--ls-wide);
  text-transform: uppercase;
  color: var(--color-grey-light);
  margin-bottom: var(--space-xs);
}

.ask-head {
  color: var(--color-platinum-dark);
}

.bid-head {
  color: var(--color-gold);
}

.level {
  position: relative;
  display: flex;
  justify-content: space-between;
  gap: var(--space-xs);
  padding: 4px var(--space-xs);
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  overflow: hidden;
}

/* Фон строки — «глубина» стакана: золото для bid, платина для ask */
.qty-bar {
  position: absolute;
  inset: 0 auto 0 0;
  opacity: 0.15;
}

.bid-bar {
  background: var(--color-gold);
}

.ask-bar {
  background: var(--color-platinum-dark);
}

.price {
  position: relative;
  color: var(--color-ink);
}

.qty {
  position: relative;
  color: var(--color-grey);
}

.divider {
  width: 1px;
  background: var(--color-platinum);
}

/* ---------- Адаптив: на планшете — одна колонка ---------- */
@media (max-width: 1023px) {
  .volumes-row {
    grid-template-columns: 1fr;
  }
}
</style>