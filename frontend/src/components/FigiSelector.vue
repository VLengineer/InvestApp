<script setup lang="ts">
/**
 * FigiSelector.vue — ключевой элемент дашборда: минималистичный dropdown
 * FIGI (Modern Platinum: белый фон, тонкая платиновая рамка, золото —
 * только точечный акцент: label, active-строка).
 *
 * ВАЖНО ПРО СЛОИ (z-index).
 * Панель списка рендерится через <Teleport to="body"> и имеет
 * position: fixed. Причина: секции дашборда (.filters с animate-hero,
 * .chart-section с isolation/.reveal) создают собственные стековые
 * контексты — любой z-index внутри секции фильтров «запирается» в нём и
 * перекрывается идущими позже в DOM канвасами графиков, сколько бы он ни
 * был. Teleport выносит панель в корневой стековый контекст документа,
 * поэтому она гарантированно поверх графиков и не обрезается
 * скролл-контейнером (.app-content { overflow-x: auto }).
 *
 * Компонент умеет:
 *  - показывать список уникальных FIGI (данные приходят из props);
 *  - искать по вводу (фильтр), чтобы не прокручивать длинный список;
 *  - авто-flip вверх, если внизу экрана не хватает места;
 *  - «прилипать» к триггеру при скролле/ресайзе;
 *  - закрытие по клику вне, Enter/Escape, стрелки вверх/вниз.
 */
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'

const props = defineProps<{
  /** Доступные FIGI из БД. */
  figis: string[]
  /** Текущий выбранный FIGI (v-model). */
  modelValue: string
  /** true — список ещё загружается. */
  loading?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

/** Отступ панели от триггера и от краёв вьюпорта, px. */
const GAP = 6
const VIEWPORT_PADDING = 12
/** Желаемая высота списка (совпадает с max-height в CSS). */
const IDEAL_HEIGHT = 260

const open = ref(false)
const rootEl = ref<HTMLElement | null>(null)
const triggerEl = ref<HTMLElement | null>(null)
const panelEl = ref<HTMLElement | null>(null)
const searchEl = ref<HTMLInputElement | null>(null)

const search = ref('')
const highlighted = ref(0)

/** Инлайновые стили фиксированной панели (пересчитываются при каждом open/scroll). */
const panelStyle = ref<Record<string, string>>({})

/** Отфильтрованный список (поиск подстрокой без регистра). */
const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  return q ? props.figis.filter((f) => f.toLowerCase().includes(q)) : props.figis
})

/**
 * Позиционирование панели относительно триггера.
 * Считаем от координат триггера: при открытии вниз якорь — `top`,
 * при открытии вверх — `bottom` (панель растёт вверх, измерять её высоту
 * заранее не нужно — ограничения задаются через max-height).
 */
function positionPanel() {
  const trigger = triggerEl.value
  if (!trigger) return

  const rect = trigger.getBoundingClientRect()
  const spaceBelow = window.innerHeight - rect.bottom - GAP - VIEWPORT_PADDING
  const spaceAbove = rect.top - GAP - VIEWPORT_PADDING
  const flipUp = spaceBelow < Math.min(IDEAL_HEIGHT, 160) && spaceAbove > spaceBelow

  const width = Math.max(rect.width, 240)
  const left = Math.min(Math.max(rect.left, VIEWPORT_PADDING), window.innerWidth - width - VIEWPORT_PADDING)

  const next: Record<string, string> = {
    left: `${left}px`,
    width: `${width}px`,
    position: 'fixed',
  }

  if (flipUp) {
    next.top = 'auto'
    next.bottom = `${window.innerHeight - rect.top + GAP}px`
    next.maxHeight = `${Math.max(spaceAbove, 120)}px`
  } else {
    next.top = `${rect.bottom + GAP}px`
    next.bottom = 'auto'
    next.maxHeight = `${Math.max(spaceBelow, 120)}px`
  }

  panelStyle.value = next
}

/** Перепозиционирование при скролле любого предка и при ресайзе окна. */
function onReflow() {
  if (open.value) positionPanel()
}

/** Клик вне компонента (в т.ч. по teleported-панели) закрывает dropdown. */
function onDocPointerDown(ev: MouseEvent) {
  if (!open.value) return
  const target = ev.target as Node | null
  if (!target) return
  if (rootEl.value?.contains(target)) return // триггер — обработка своя
  if (panelEl.value?.contains(target)) return // клик по опциям/поиску
  close()
}

function addReflowListeners() {
  // capture: true — ловим scroll и у внутренних скролл-контейнеров (.app-content)
  window.addEventListener('scroll', onReflow, { capture: true, passive: true })
  window.addEventListener('resize', onReflow)
}

function removeReflowListeners() {
  window.removeEventListener('scroll', onReflow, { capture: true })
  window.removeEventListener('resize', onReflow)
}

async function openList() {
  if (open.value) return
  // Координаты считаем ДО показа: панель получает инлайновый position/fixed
  // уже на первом рендере, без «мигания» в начале документа.
  search.value = ''
  highlighted.value = Math.max(0, filtered.value.indexOf(props.modelValue))
  positionPanel()

  open.value = true
  await nextTick()
  addReflowListeners()
  // autofocus на динамически вставленном узле ненадёжен — фокус ставим явно
  searchEl.value?.focus()
}

function close(restoreFocus = false) {
  if (!open.value) return
  open.value = false
  search.value = ''
  removeReflowListeners()
  if (restoreFocus) triggerEl.value?.focus()
}

function toggle() {
  if (open.value) close(true)
  else void openList()
}

function select(figi: string) {
  emit('update:modelValue', figi)
  close(true)
}

/** Прокрутка списка, чтобы активная строка не уходила за край видимой области. */
function scrollHighlightIntoView() {
  const list = panelEl.value?.querySelector<HTMLElement>('.list')
  const item = list?.querySelector<HTMLElement>('.item--highlight')
  item?.scrollIntoView({ block: 'nearest' })
}

function onKeydown(ev: KeyboardEvent) {
  if (!open.value) {
    if (ev.key === 'Enter' || ev.key === 'ArrowDown' || ev.key === ' ') {
      ev.preventDefault()
      void openList()
    }
    return
  }
  switch (ev.key) {
    case 'Escape':
      ev.preventDefault()
      close(true)
      break
    case 'ArrowDown':
      ev.preventDefault()
      highlighted.value = Math.min(highlighted.value + 1, filtered.value.length - 1)
      void nextTick(scrollHighlightIntoView)
      break
    case 'ArrowUp':
      ev.preventDefault()
      highlighted.value = Math.max(highlighted.value - 1, 0)
      void nextTick(scrollHighlightIntoView)
      break
    case 'Enter': {
      ev.preventDefault()
      const figi = filtered.value[highlighted.value]
      if (figi) select(figi)
      break
    }
    case 'Tab':
      close()
      break
  }
}

window.addEventListener('mousedown', onDocPointerDown)
onBeforeUnmount(() => {
  window.removeEventListener('mousedown', onDocPointerDown)
  removeReflowListeners()
})
</script>

<template>
  <div ref="rootEl" class="figi-selector">
    <button
      ref="triggerEl"
      type="button"
      class="trigger"
      :disabled="loading || figis.length === 0"
      :aria-expanded="open"
      aria-haspopup="listbox"
      @click="toggle"
      @keydown="onKeydown"
    >
      <span class="trigger-label">FIGI</span>
      <span class="trigger-value">{{ modelValue || (loading ? 'Загрузка…' : 'Выберите инструмент') }}</span>
      <span class="chevron" :class="{ 'chevron--open': open }" aria-hidden="true">▾</span>
    </button>

    <!-- Панель вне DOM-иерархии секций: только так она гарантированно
         поверх канвасов графиков (см. комментарий в <script>). -->
    <Teleport to="body">
      <div
        v-if="open"
        ref="panelEl"
        class="panel animate-dropdown"
        :style="panelStyle"
        role="presentation"
      >
        <input
          ref="searchEl"
          v-model="search"
          class="search"
          type="text"
          placeholder="Поиск по FIGI…"
          aria-label="Поиск по FIGI"
          @keydown="onKeydown"
        />
        <ul class="list" role="listbox">
          <li
            v-for="(figi, i) in filtered.slice(0, 200)"
            :key="figi"
            role="option"
            :aria-selected="figi === modelValue"
            class="item"
            :class="{
              'item--active': figi === modelValue,
              'item--highlight': i === highlighted,
            }"
            @click="select(figi)"
          >
            {{ figi }}
          </li>
          <li v-if="filtered.length === 0" class="empty">Ничего не найдено</li>
        </ul>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
/* Flat-стиль: тонкие линии, радиус 2px, без теней в покое;
   золото — точечный акцент. Только токены из tokens.css. */
.figi-selector {
  position: relative;
  min-width: 240px;
}

.trigger {
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: 10px var(--space-sm);
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-platinum);
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--color-ink);
  transition: border-color var(--duration-fast) var(--ease-out);
}

.trigger:hover:not(:disabled) {
  border-color: var(--color-gold);
}

.trigger:focus-visible {
  outline: none;
  border-color: var(--color-gold);
}

.trigger:disabled {
  cursor: default;
  opacity: 0.6;
}

.trigger-label {
  font-size: var(--fs-micro);
  font-weight: var(--fw-medium);
  letter-spacing: var(--ls-wide);
  text-transform: uppercase;
  color: var(--color-gold);
}

.trigger-value {
  flex: 1;
  text-align: left;
  font-size: var(--fs-small);
  font-weight: var(--fw-light);
  letter-spacing: var(--ls-tight);
}

/* Шеврон — лёгкий поворот (плавно, без bounce) */
.chevron {
  color: var(--color-grey-light);
  transition: transform var(--duration-fast) var(--ease-out);
}

.chevron--open {
  transform: rotate(180deg);
}

/* position/left/top/width/max-height приходят из panelStyle (fixed, Teleport).
   --z-dropdown выше канвасов графиков и ниже модалки (--z-overlay). */
.panel {
  z-index: var(--z-dropdown);
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-platinum-dark);
  border-radius: var(--radius-sm);
  box-shadow: var(--shadow-soft); /* тень только у «поднятого» слоя */
  overflow: hidden;
}

.search {
  width: 100%;
  padding: var(--space-xs) var(--space-sm);
  border: none;
  border-bottom: 1px solid var(--color-platinum);
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  outline: none;
  background: var(--color-platinum-soft);
  color: var(--color-ink);
}

.search:focus {
  background: var(--color-gold-soft);
}

/* max-height переопределяется инлайново (доступное место во вьюпорте) */
.list {
  list-style: none;
  margin: 0;
  padding: var(--space-xs) 0;
  max-height: 260px;
  overflow-y: auto;
}

.item {
  padding: var(--space-xs) var(--space-sm);
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  letter-spacing: var(--ls-tight);
  cursor: pointer;
  color: var(--color-grey);
  transition:
    color var(--duration-fast) var(--ease-out),
    background-color var(--duration-fast) var(--ease-out);
}

.item:hover,
.item--highlight {
  background: var(--color-platinum-soft);
  color: var(--color-gold-hover);
}

/* Активная строка — золотая линия слева */
.item--active {
  color: var(--color-ink);
  border-left: 2px solid var(--color-gold);
  font-weight: var(--fw-regular);
}

.empty {
  padding: var(--space-xs) var(--space-sm);
  font-size: var(--fs-micro);
  font-weight: var(--fw-light);
  color: var(--color-grey-light);
}
</style>
