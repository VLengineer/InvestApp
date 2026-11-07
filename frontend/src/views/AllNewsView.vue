<script setup lang="ts">
/**
 * AllNewsView.vue — страница «Аналитика новостей»:
 *  - Пагинация (limit/offset) через GET /api/market/all-news;
 *  - Карточки в стиле Dashboard (золотые акценты, платиновый фон);
 *  - Клик по карточке → NewsModal (идентичен модалке Dashboard).
 */
import { computed, onMounted, ref, watch } from 'vue'
import type { MarketDataItem } from '../types/market'
import { fetchAllNews, fetchNewsById } from '../api/market'
import NewsModal from '../components/NewsModal.vue'

const PAGE_SIZE = 20

const items = ref<MarketDataItem[]>([])
const total = ref(0)
const offset = ref(0)
const loading = ref(false)
const error = ref('')

const currentPage = computed(() => Math.floor(offset.value / PAGE_SIZE) + 1)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

const selectedNews = ref<MarketDataItem | null>(null)

async function loadNews() {
  loading.value = true
  error.value = ''
  try {
    const data = await fetchAllNews(PAGE_SIZE, offset.value)
    items.value = data.items
    total.value = data.total
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'Ошибка загрузки'
  } finally {
    loading.value = false
  }
}

function goToPage(page: number) {
  if (page < 1 || page > totalPages.value) return
  offset.value = (page - 1) * PAGE_SIZE
}

async function openModal(item: MarketDataItem) {
  try {
    const data = await fetchNewsById(item.id)
    selectedNews.value = data.news
  } catch (e: unknown) {
    console.error('Failed to load news details:', e)
    error.value = 'Не удалось загрузить детали новости'
  }
}

function closeModal() {
  selectedNews.value = null
}

/** Форматирование даты из ISO-строки. */
function formatDate(iso: string | null): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('ru-RU', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

/** Цветовой класс для sentiment. */
function sentimentClass(score: number | null): string {
  if (score === null || score === undefined) return 'badge--neutral'
  if (score >= 0.3) return 'badge--positive'
  if (score <= -0.3) return 'badge--negative'
  return 'badge--neutral'
}

/** Подпись для sentiment. */
function sentimentLabel(score: number | null): string {
  if (score === null || score === undefined) return '—'
  if (score >= 0.3) return 'Позитивный'
  if (score <= -0.3) return 'Негативный'
  return 'Нейтральный'
}

/** Цветовой класс для expected impact. */
function impactClass(impact: number | null): string {
  if (impact === null || impact === undefined) return 'badge--neutral'
  if (impact >= 2) return 'badge--positive'
  if (impact >= 1) return 'badge--warning'
  return 'badge--negative'
}

function impactLabel(impact: number | null): string {
  if (impact === null || impact === undefined) return '—'
  if (impact >= 2) return 'Высокий'
  if (impact >= 1) return 'Средний'
  return 'Низкий'
}

/** Обрезать текст до N символов. */
function truncate(text: string | null, maxLen: number): string {
  if (!text) return ''
  return text.length > maxLen ? text.slice(0, maxLen) + '…' : text
}

/** Декодирование HTML-сущностей (\", \', \\, &quot; и т.д.). */
function unescapeHtml(text: string | null): string {
  if (!text) return ''
  const doc = new DOMParser().parseFromString(text, 'text/html')
  return doc.documentElement.textContent || ''
}


onMounted(() => {
  loadNews()
})

watch(offset, () => {
  loadNews()
})
</script>

<template>
  <div class="all-news-view">
    <!-- Заголовок -->
    <div class="page-header">
      <h1 class="page-title">Аналитика новостей</h1>
      <p class="page-subtitle">
        Все новости из базы данных с ИИ-анализом. Всего записей: <strong>{{ total }}</strong>
      </p>
    </div>

    <!-- Ошибка -->
    <div v-if="error" class="error-banner">
      <span>{{ error }}</span>
      <button class="retry-btn" @click="loadNews">Повторить</button>
    </div>

    <!-- Загрузка -->
    <div v-if="loading && items.length === 0" class="loading-state">
      <div class="spinner"></div>
      <span>Загрузка новостей…</span>
    </div>

    <!-- Список карточек -->
    <div v-if="items.length > 0" class="news-grid">
      <article
        v-for="item in items"
        :key="item.id"
        class="news-card"
        @click="openModal(item)"
      >
        <!-- Заголовок + дата -->
        <div class="card-header">
          <h3 class="card-title">{{ unescapeHtml(item.title) || 'Без заголовка' }}</h3>
          <time class="card-date">{{ formatDate(item.ts) }}</time>
        </div>

        <!-- Источник + FIGI -->
        <div class="card-meta">
          <span v-if="item.source" class="meta-tag">{{ item.source }}</span>
          <span v-if="item.figi" class="meta-tag meta-tag--figi">{{ item.figi }}</span>
        </div>

        <!-- Саммари ИИ -->
        <p v-if="item.ai_text_summary" class="card-summary">
          {{ truncate(unescapeHtml(item.ai_text_summary), 200) }}
        </p>
        <p v-else class="card-summary card-summary--empty">
          {{ truncate(unescapeHtml(item.content), 200) }}
        </p>

        <!-- Бейджи аналитики -->
        <div class="card-badges">
          <span class="badge" :class="sentimentClass(item.ai_sentiment_score)">
            Sentiment: {{ sentimentLabel(item.ai_sentiment_score) }}
          </span>
          <span class="badge" :class="impactClass(item.ai_expected_impact)">
            Impact: {{ impactLabel(item.ai_expected_impact) }}
          </span>
          <span v-if="item.close_price" class="badge badge--price">
            Цена: {{ item.close_price.toFixed(2) }} {{ item.price_currency || '' }}
          </span>
        </div>
      </article>
    </div>

    <!-- Пустое состояние -->
    <div v-if="!loading && items.length === 0 && !error" class="empty-state">
      <p>Новости не найдены.</p>
    </div>

    <!-- Пагинация -->
    <div v-if="totalPages > 1" class="pagination">
      <button
        class="pagination-btn"
        :disabled="currentPage <= 1"
        @click="goToPage(currentPage - 1)"
      >
        ← Назад
      </button>
      <span class="pagination-info">
        Страница {{ currentPage }} из {{ totalPages }}
      </span>
      <button
        class="pagination-btn"
        :disabled="currentPage >= totalPages"
        @click="goToPage(currentPage + 1)"
      >
        Вперёд →
      </button>
    </div>

    <!-- Модалка (идентична Dashboard) -->
    <NewsModal :news="selectedNews" @close="closeModal" />
  </div>
</template>

<style scoped>
.all-news-view {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px 16px;
}

/* ===== Заголовок ===== */
.page-header {
  margin-bottom: 24px;
}

.page-title {
  font-size: 1.75rem;
  font-weight: 600;
  color: var(--color-text-primary, #1a1a2e);
  margin: 0 0 8px;
}

.page-subtitle {
  font-size: 0.9rem;
  color: var(--color-text-secondary, #6b7280);
  margin: 0;
}

.page-subtitle strong {
  color: var(--color-accent-gold, #b8860b);
}

/* ===== Ошибка ===== */
.error-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  color: #991b1b;
  margin-bottom: 16px;
}

.retry-btn {
  padding: 4px 12px;
  font-size: 0.8rem;
  background: #991b1b;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

/* ===== Загрузка ===== */
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 48px 0;
  color: var(--color-text-secondary, #6b7280);
}

.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid #e5e7eb;
  border-top-color: var(--color-accent-gold, #b8860b);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ===== Сетка карточек ===== */
.news-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

/* ===== Карточка ===== */
.news-card {
  background: var(--color-surface, #ffffff);
  border: 1px solid var(--color-border, #e5e7eb);
  border-radius: 10px;
  padding: 16px;
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.news-card:hover {
  border-color: var(--color-accent-gold, #b8860b);
  box-shadow: 0 2px 8px rgba(184, 134, 11, 0.08);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}

.card-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--color-text-primary, #1a1a2e);
  margin: 0;
  line-height: 1.3;
  flex: 1;
}

.card-date {
  font-size: 0.75rem;
  color: var(--color-text-secondary, #6b7280);
  white-space: nowrap;
  flex-shrink: 0;
}

/* ===== Мета-теги ===== */
.card-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.meta-tag {
  font-size: 0.7rem;
  padding: 2px 8px;
  border-radius: 4px;
  background: #f3f4f6;
  color: #4b5563;
}

.meta-tag--figi {
  background: #fef3c7;
  color: #92400e;
}

/* ===== Саммари ===== */
.card-summary {
  font-size: 0.82rem;
  color: var(--color-text-secondary, #6b7280);
  line-height: 1.5;
  margin: 0;
}

.card-summary--empty {
  font-style: italic;
  opacity: 0.7;
}

/* ===== Бейджи ===== */
.card-badges {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: auto;
}

.badge {
  font-size: 0.7rem;
  padding: 2px 8px;
  border-radius: 4px;
  background: #f3f4f6;
  color: #4b5563;
}

.badge--positive {
  background: #dcfce7;
  color: #166534;
}

.badge--negative {
  background: #fef2f2;
  color: #991b1b;
}

.badge--warning {
  background: #fef3c7;
  color: #92400e;
}

.badge--neutral {
  background: #f3f4f6;
  color: #6b7280;
}

.badge--price {
  background: #eff6ff;
  color: #1e40af;
}

/* ===== Пустое состояние ===== */
.empty-state {
  text-align: center;
  padding: 48px 0;
  color: var(--color-text-secondary, #6b7280);
}

/* ===== Пагинация ===== */
.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 16px 0;
}

.pagination-btn {
  padding: 8px 16px;
  font-size: 0.85rem;
  background: var(--color-surface, #ffffff);
  border: 1px solid var(--color-border, #e5e7eb);
  border-radius: 6px;
  cursor: pointer;
  color: var(--color-text-primary, #1a1a2e);
  transition: border-color 0.2s;
}

.pagination-btn:hover:not(:disabled) {
  border-color: var(--color-accent-gold, #b8860b);
}

.pagination-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.pagination-info {
  font-size: 0.85rem;
  color: var(--color-text-secondary, #6b7280);
}
</style>
