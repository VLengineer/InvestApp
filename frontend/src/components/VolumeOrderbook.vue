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

const GOLD = '#D4AF37'
const TEXT_SECONDARY = '#6B6B6B'

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
      axisLine: { lineStyle: { color: '#E5E4E2' } },
      axisTick: { show: false },
      axisLabel: { color: TEXT_SECONDARY, fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: '#F5F5F4' } },
      axisLabel: { color: TEXT_SECONDARY, fontSize: 10 },
    },
    series: [
      { name: 'Volume', type: 'bar', data: total, itemStyle: { color: 'rgba(212,175,55,0.45)' }, barWidth: '70%' },
      { name: 'Buy', type: 'bar', data: buy, itemStyle: { color: GOLD }, stack: 'bs' },
      { name: 'Sell', type: 'bar', data: sell, itemStyle: { color: '#B8B7B5' }, stack: 'bs' },
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

let onResize: (() => void) | null = null

onMounted(() => {
  if (volEl.value) {
    volChart = echarts.init(volEl.value, undefined, { renderer: 'canvas' })
    renderVolumes(props.data)
    onResize = () => volChart?.resize()
    window.addEventListener('resize', onResize)
  }
})

onBeforeUnmount(() => {
  if (onResize) window.removeEventListener('resize', onResize)
  volChart?.dispose()
  volChart = null
})

watch(() => props.data, (items) => renderVolumes(items))
</script>

<template>
  <div class="volumes-row">
    <!-- Объёмы -->
    <section class="card">
      <h3 class="block-title">Объёмы</h3>
      <div ref="volEl" class="vol-chart" />
    </section>

    <!-- Стакан -->
    <section class="card book-card">
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
.volumes-row {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr);
  gap: 16px;
}

@media (max-width: 1279px) {
  .volumes-row {
    grid-template-columns: 1fr;
  }
}

.card {
  background: #ffffff;
  border: 1px solid var(--color-platinum, #e5e4e2);
  border-radius: 8px;
  padding: 16px;
  min-width: 0;
}

.block-title {
  margin: 0 0 12px;
  font-size: 15px;
  font-weight: 400;
  letter-spacing: 0.03em;
  color: var(--color-text-primary, #1a1a1a);
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.depth-badge {
  font-size: 11px;
  font-weight: 300;
  color: var(--color-gold-dark, #a8871c);
  border: 1px solid var(--color-gold-light, #f4e5b8);
  border-radius: 999px;
  padding: 1px 8px;
}

.vol-chart {
  height: 180px;
  width: 100%;
}

.book-empty {
  font-size: 13px;
  font-weight: 300;
  color: var(--color-text-secondary, #6b6b6b);
  padding: 20px 0;
  text-align: center;
}

.book {
  display: flex;
  gap: 12px;
}

.book-col {
  flex: 1;
  min-width: 0;
}

.col-head {
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 6px;
}

.ask-head { color: #c0392b; }
.bid-head { color: #3e8e5a; }

.level {
  position: relative;
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 3px 6px;
  font-size: 12px;
  font-weight: 300;
  color: var(--color-text-primary, #1a1a1a);
  overflow: hidden;
  border-radius: 3px;
}

.qty-bar {
  position: absolute;
  inset-block: 0;
  left: 0;
  opacity: 0.18;
}

.ask-bar { background: #c0392b; }
.bid-bar { background: #3e8e5a; }

.price { z-index: 1; font-variant-numeric: tabular-nums; }
.qty { z-index: 1; color: var(--color-text-secondary, #6b6b6b); font-variant-numeric: tabular-nums; }

.divider {
  width: 1px;
  background: var(--color-gold-light, #f4e5b8);
}
</style>
