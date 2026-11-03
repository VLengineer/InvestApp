<script setup lang="ts">
/**
 * Dashboard.vue — финансовый дашборд (новый, по ТЗ).
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
import type { MarketDataItem } from '../types/market'

const route = useRoute()
const router = useRouter()

const LS_KEY = 'dashboard.figi'

/* ------------------- Состояние ------------------- */

const figis = ref<string[]>([])
const figisLoading = ref(true)
const selectedFigi = ref('')
const history = shallowRef<MarketDataItem[]>([])
const loadingHistory = ref(false)
const error = ref('')

const priceChartRef = ref<InstanceType<typeof PriceChart> | null>(null)

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

watch(selectedFigi, async (figi, prev) => {
  if (!figi || figi === prev) return
  // 1. История по REST (последние 500)
  await loadHistory(figi)
  // 2. Переподписка WebSocket (сервер сам отпишет от предыдущего FIGI)
  subscribe(figi)
  // 3. URL (?figi=) + localStorage — чтобы ссылкой можно было делиться
  if (route.query.figi !== figi) {
    router.replace({ query: { ...route.query, figi } })
  }
  try {
    localStorage.setItem(LS_KEY, figi)
  } catch {
    /* приватный режим — игнорируем */
  }
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

onMounted(async () => {
  try {
    figis.value = await fetchFigis()
  } catch (e) {
    error.value = `Не удалось получить список FIGI: ${e instanceof Error ? e.message : String(e)}`
  } finally {
    figisLoading.value = false
  }
  if (figis.value.length === 0) return

  // Приоритет выбора: ?figi= из URL → localStorage → первый из списка
  const fromUrl = typeof route.query.figi === 'string' ? route.query.figi : ''
  let stored = ''
  try {
    stored = localStorage.getItem(LS_KEY) || ''
  } catch {
    /* noop */
  }
  const initial =
    fromUrl && figis.value.includes(fromUrl)
      ? fromUrl
      : stored && figis.value.includes(stored)
        ? stored
        : figis.value[0]
  selectedFigi.value = initial
})
</script>

<template>
  <div class="dashboard">
    <!-- Фильтры -->
    <section class="filters card">
      <div class="filter-group">
        <FigiSelector v-model="selectedFigi" :figis="figis" :loading="figisLoading" />
      </div>
      <div class="filter-group period-group">
        <label class="field-label" for="period">Период</label>
        <select id="period" v-model.number="periodHours" class="period-select">
          <option v-for="p in PERIODS" :key="p.hours" :value="p.hours">{{ p.label }}</option>
        </select>
      </div>
      <div class="status">
        <span class="dot" :class="connected ? 'dot--on' : 'dot--off'" />
        {{ connected ? 'Real-time активен' : 'Ожидание соединения' }}
      </div>
    </section>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="loadingHistory" class="loading">Загрузка данных…</p>

    <template v-if="selectedFigi">
      <!-- График цены с маркерами новостей -->
      <PriceChart ref="priceChartRef" :data="visibleHistory" @marker-click="openNewsModal" />

      <!-- Аналитика ИИ (последняя запись с саммари) -->
      <AICard :data="visibleHistory" />

      <!-- Осцилляторы -->
      <OscillatorCharts :data="visibleHistory" />

      <!-- Объёмы и стакан -->
      <VolumeOrderbook :data="visibleHistory" />
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
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 24px;
  max-width: 1920px;
  min-width: 1024px; /* корректное отображение от 1280px с учётом сайдбара */
}

.card {
  background: #ffffff;
  border: 1px solid var(--color-platinum, #e5e4e2);
  border-radius: 8px;
  padding: 16px;
}

.filters {
  display: flex;
  align-items: flex-end;
  gap: 24px;
  flex-wrap: wrap;
}

.field-label {
  display: block;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--color-text-secondary, #6b6b6b);
  margin-bottom: 6px;
}

.period-select {
  appearance: none;
  padding: 10px 32px 10px 14px;
  font: inherit;
  font-size: 14px;
  font-weight: 300;
  color: var(--color-text-primary, #1a1a1a);
  background: #ffffff
    url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6'><path d='M0 0l5 6 5-6z' fill='%23A8871C'/></svg>")
    no-repeat right 12px center;
  border: 1px solid var(--color-platinum-dark, #b8b7b5);
  border-radius: 6px;
  cursor: pointer;
}

.period-select:focus {
  outline: none;
  border-color: var(--color-gold, #d4af37);
}

.status {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 300;
  color: var(--color-text-secondary, #6b6b6b);
  padding-bottom: 10px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.dot--on { background: var(--color-gold, #d4af37); }
.dot--off { background: var(--color-platinum-dark, #b8b7b5); }

.error {
  margin: 0;
  font-size: 13px;
  color: #c0392b;
  border: 1px solid #f0c9c2;
  border-radius: 6px;
  padding: 8px 12px;
  background: #fff;
}

.loading {
  margin: 0;
  font-size: 13px;
  font-weight: 300;
  color: var(--color-text-secondary, #6b6b6b);
}

.empty {
  font-size: 14px;
  font-weight: 300;
  color: var(--color-text-secondary, #6b6b6b);
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}
</style>
