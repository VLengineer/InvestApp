<script setup lang="ts">
/**
 * Dashboard.vue — финансовый дашборд в стиле «Modern Platinum».
 *
 * Поток данных:
 *  1. GET /api/market/figis        → список FIGI в селектор;
 *  2. выбор FIGI (или ?figi= из URL / localStorage) →
 *     GET /api/market/initial-data?figi=… → последние 500 записей → графики;
 *  3. WebSocket subscribe(figi) → new_data → upsert свечи/осцилляторы/объёмы;
 *  4. клик по золотому маркеру → GET /api/market/news/{id} → NewsModal.
 *
 * Выбранный FIGI сохраняется в query-параметр ?figi= (шаринг ссылки)
 * и в localStorage (дефолт при следующем визите).
 * Секции появляются при скролле через composable useRevealOnScroll.
 */
import { onMounted, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import FigiSelector from '../components/FigiSelector.vue'
import PriceChart from '../components/PriceChart.vue'
import OscillatorCharts from '../components/OscillatorCharts.vue'
import VolumeOrderbook from '../components/VolumeOrderbook.vue'
import AICard from '../components/AICard.vue'
import NewsModal from '../components/NewsModal.vue'
import { fetchFigis, fetchInitialData, fetchNewsById } from '../api/market'
import { useWebSocket } from '../composables/useWebSocket'
import { useRevealOnScroll } from '../composables/useRevealOnScroll'
import type { MarketDataItem } from '../types/market'
import type { ChartSync } from '../composables/useChartSync'

const route = useRoute()
const router = useRouter()

const { revealRef } = useRevealOnScroll()

const LS_KEY = 'dashboard.figi'

/* ------------------- Состояние ------------------- */

const figis = ref<string[]>([])
const figisLoading = ref(true)
const selectedFigi = ref('')
const history = shallowRef<MarketDataItem[]>([])
const loadingHistory = ref(false)
const error = ref('')

const priceChartRef = ref<InstanceType<typeof PriceChart> | null>(null)

/** Общий барабан времени (свечи ⇄ осцилляторы): зум/скролл/кроссхэйр. */
const chartSync = shallowRef<ChartSync | null>(null)

/* Модалка новости */
const modalNews = shallowRef<MarketDataItem | null>(null)
const modalLoading = ref(false)

/* Период отображения истории (фильтр по времени, данные не перезапрашиваются) */
const PERIODS = [
  { label: '1 день', hours: 24 },
  { label: '3 дня', hours: 72 },
  { label: '7 дней', hours: 168 },
  { label: 'Вся история', hours: 0 },
] as const
const periodHours = ref<number>(0)

/** История с учётом выбранного периода (срез по времени последних записей). */
const visibleHistory = shallowRef<MarketDataItem[]>([])

function applyPeriod() {
  if (periodHours.value === 0) {
    visibleHistory.value = history.value
    return
  }
  const cutoff = Date.now() - periodHours.value * 3600_000
  visibleHistory.value = history.value.filter((it) => {
    const t = it.candle_time ?? it.ts
    return t ? new Date(t).getTime() >= cutoff : true
  })
}

watch([history, periodHours], applyPeriod)

/* ------------------- Real-time (WebSocket) ------------------- */

function onNewData(item: MarketDataItem) {
  // Только данные текущего FIGI (сервер фильтрует, но перестрахуемся)
  if (selectedFigi.value && item.figi && item.figi !== selectedFigi.value) return

  // 1. Обновляем историю (append или замена свечи с тем же candle_time)
  const arr = history.value.slice()
  const key = item.candle_time ?? item.ts
  const idx = key ? arr.findIndex((x) => (x.candle_time ?? x.ts) === key && x.id !== item.id) : -1
  if (idx >= 0) arr[idx] = item
  else arr.push(item)
  // Не держим больше 500 точек на экране (ТЗ: не грузить более 500 свечей)
  history.value = arr.length > 500 ? arr.slice(arr.length - 500) : arr

  // 2. Цена + маркеры — императивный upsert без полной перерисовки
  priceChartRef.value?.upsert(item)
}

const { connected, subscribe } = useWebSocket(onNewData)

/* ------------------- Логика смены FIGI ------------------- */

async function loadHistory(figi: string) {
  loadingHistory.value = true
  error.value = ''
  try {
    const res = await fetchInitialData(figi)
    history.value = res.data
  } catch (e) {
    error.value = `Не удалось загрузить данные: ${e instanceof Error ? e.message : String(e)}`
    history.value = []
  } finally {
    loadingHistory.value = false
  }
}

/**
 * Смена FIGI через селектор. Первичный FIGI грузится в initDashboard()
 * (watch не вызывается на инициальное значение), поэтому здесь guard
 * `figi === prev` защищает от двойной загрузки только при явных повторах.
 */
watch(selectedFigi, async (figi, prev) => {
  if (!figi || figi === prev) return
  // 1. История по REST (последние 500)
  await loadHistory(figi)
  // 2. Переподписка WebSocket (сервер сам отпишет от предыдущего FIGI)
  subscribe(figi)
  // 3. URL (?figi=) + localStorage — чтобы ссылкой можно было делиться
  persistFigi(figi)
})

/* ------------------- Модалка новости ------------------- */

async function openNewsModal(newsId: string) {
  modalLoading.value = true
  try {
    const res = await fetchNewsById(newsId)
    modalNews.value = res.news
  } catch (e) {
    error.value = `Не удалось загрузить новость: ${e instanceof Error ? e.message : String(e)}`
  } finally {
    modalLoading.value = false
  }
}

/* ------------------- Инициализация ------------------- */

/**
 * Фиги, которые есть в списке БД, но по которым initial-data вернул 404
 * (данные только что удалили/мигрировали — гонка между /figis и /initial-data).
 * Нужны, чтобы не зациклить onMounted: без этого дашборд падал в белый экран
 * при пустом history у валидного FIGI.
 */
const brokenFigis = ref<Set<string>>(new Set())

async function initDashboard(): Promise<void> {
  try {
    figis.value = await fetchFigis()
  } catch (e) {
    error.value = `Не удалось получить список FIGI: ${e instanceof Error ? e.message : String(e)}`
    figisLoading.value = false
    return
  }
  figisLoading.value = false
  if (figis.value.length === 0) return

  // Приоритет выбора: ?figi= из URL → localStorage → первый из списка
  const fromUrl = typeof route.query.figi === 'string' ? route.query.figi : ''
  let stored = ''
  try {
    stored = localStorage.getItem(LS_KEY) || ''
  } catch {
    /* noop */
  }
  const candidates = [fromUrl, stored, ...figis.value]
  const initial = candidates.find(
    (f) => f && figis.value.includes(f) && !brokenFigis.value.has(f),
  )
  if (!initial) return
  selectedFigi.value = initial

  // Явная первичная загрузка + подписка WS.
  // Watch на selectedFigi срабатывает только при ИЗМЕНЕНИИ значения, поэтому
  // стартовый FIGI грузим здесь — иначе страница рендерилась бы пустой.
  await loadHistory(initial)
  subscribe(initial)
  persistFigi(initial)
}

/** Сохранение выбранного FIGI в URL (?figi=) и localStorage (шаринг ссылки). */
function persistFigi(figi: string) {
  if (route.query.figi !== figi) {
    router.replace({ query: { ...route.query, figi } })
  }
  try {
    localStorage.setItem(LS_KEY, figi)
  } catch {
    /* приватный режим — игнорируем */
  }
}

onMounted(() => initDashboard())
</script>

<template>
  <div ref="revealRef" class="dashboard">
    <!-- Фильтры -->
    <section class="filters card pl-card animate-hero" aria-label="Фильтры данных">
      <div class="filter-group">
        <FigiSelector v-model="selectedFigi" :figis="figis" :loading="figisLoading" />
      </div>
      <div class="filter-group period-group">
        <label class="field-label" for="period">Период</label>
        <select id="period" v-model.number="periodHours" class="period-select">
          <option v-for="p in PERIODS" :key="p.hours" :value="p.hours">{{ p.label }}</option>
        </select>
      </div>
      <div class="status" role="status">
        <span class="dot" :class="connected ? 'dot--on' : 'dot--off'" />
        {{ connected ? 'Real-time активен' : 'Ожидание соединения' }}
      </div>
    </section>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="loadingHistory" class="loading">Загрузка данных…</p>

    <template v-if="selectedFigi">
      <!-- График цены с маркерами новостей -->
      <PriceChart
        ref="priceChartRef"
        :data="visibleHistory"
        class="reveal"
        @marker-click="openNewsModal"
        @sync-ready="chartSync = $event"
      />

      <!-- Аналитика ИИ (последняя запись с саммари) -->
      <AICard :data="visibleHistory" class="reveal" />

      <!-- Осцилляторы: общий барабан времени + кроссхэйр-синхронизация со свечами -->
      <OscillatorCharts
        :data="visibleHistory"
        :sync="chartSync"
        class="reveal"
        @crosshair-time="priceChartRef?.setOscillatorCrosshair($event)"
      />

      <!-- Объёмы и стакан -->
      <VolumeOrderbook :data="visibleHistory" class="reveal" />
    </template>

    <p v-else-if="!figisLoading && figis.length === 0" class="empty">
      В базе нет данных ни по одному FIGI.
    </p>

    <!-- Модалка новости -->
    <NewsModal v-if="modalNews" :news="modalNews" @close="modalNews = null" />
    <p v-if="modalLoading" class="loading visually-hidden" aria-live="polite">Загрузка новости…</p>
  </div>
</template>

<style scoped>
/* Все цвета/отступы — токены из tokens.css. */
.dashboard {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  padding: var(--space-md);
  max-width: var(--container-max);
  margin: 0 auto;
}

.filters {
  display: flex;
  align-items: flex-end;
  gap: var(--space-md);
  flex-wrap: wrap;
  padding: var(--space-sm) var(--space-md);
}

.field-label {
  display: block;
  font-size: var(--fs-micro);
  font-weight: var(--fw-medium);
  letter-spacing: var(--ls-wide);
  text-transform: uppercase;
  color: var(--color-grey-light);
  margin-bottom: var(--space-xs);
}

.period-select {
  appearance: none;
  padding: 10px 40px 10px var(--space-sm);
  font-size: var(--fs-small);
  font-weight: var(--fw-light);
  letter-spacing: var(--ls-tight);
  color: var(--color-ink);
  background: var(--color-bg-elevated)
    url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6'><path d='M0 0l5 6 5-6z' fill='%23B8935A'/></svg>")
    no-repeat right 14px center;
  border: 1px solid var(--color-platinum);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: border-color var(--duration-fast) var(--ease-out);
}

.period-select:hover {
  border-color: var(--color-platinum-dark);
}

.period-select:focus {
  outline: none;
  border-color: var(--color-gold);
}

.status {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  letter-spacing: var(--ls-tight);
  color: var(--color-grey);
  padding-bottom: 10px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.dot--on {
  background: var(--color-gold);
}

.dot--off {
  background: var(--color-platinum-dark);
}

.error {
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  color: var(--color-ink);
  border: 1px solid var(--color-platinum);
  border-left: 2px solid var(--color-ink);
  border-radius: var(--radius-sm);
  padding: var(--space-xs) var(--space-sm);
  background: var(--color-platinum-soft);
}

.loading {
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  letter-spacing: var(--ls-tight);
  text-transform: uppercase;
  color: var(--color-grey-light);
}

.empty {
  font-size: var(--fs-small);
  font-weight: var(--fw-light);
  color: var(--color-grey);
}

/* ---------- Адаптив ---------- */
@media (max-width: 1023px) {
  .dashboard {
    padding: var(--space-sm);
    gap: var(--space-sm);
  }

  .filters {
    gap: var(--space-sm);
  }

  .status {
    margin-left: 0;
  }
}
</style>
