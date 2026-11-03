<script setup lang="ts">
/**
 * FigiSelector.vue — ключевой элемент дашборда: минималистичный dropdown
 * FIGI (Modern Platinum: белый фон, тонкая платиновая рамка, золото —
 * только точечный акцент: label, active-строка, линия снизу на hover).
 *
 * Логика инкапсулирована внутри компонента только в части отображения;
 * загрузка списка FIGI и реакция на выбор — через v-model + события родителя
 * (Dashboard.vue). Компонент умеет:
 *  - показывать список уникальных FIGI (GET /api/market/figis — данные приходят из props);
 *  - искать по вводу (фильтр), чтобы не прокручивать длинный список;
 *  - закрытие по клику вне, Enter/Escape, стрелки вверх/вниз.
 */
import { computed, onBeforeUnmount, ref } from 'vue'

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

const open = ref(false)
const rootEl = ref<HTMLElement | null>(null)
const search = ref('')
const highlighted = ref(0)

/** Отфильтрованный список (поиск подстрокой без регистра). */
const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  return q ? props.figis.filter((f) => f.toLowerCase().includes(q)) : props.figis
})

function toggle() {
  open.value = !open.value
  if (open.value) {
    search.value = ''
    highlighted.value = Math.max(0, filtered.value.indexOf(props.modelValue))
  }
}

function select(figi: string) {
  emit('update:modelValue', figi)
  open.value = false
  search.value = ''
}

function onKeydown(ev: KeyboardEvent) {
  if (!open.value) {
    if (ev.key === 'Enter' || ev.key === 'ArrowDown') {
      ev.preventDefault()
      toggle()
    }
    return
  }
  if (ev.key === 'Escape') {
    open.value = false
  } else if (ev.key === 'ArrowDown') {
    ev.preventDefault()
    highlighted.value = Math.min(highlighted.value + 1, filtered.value.length - 1)
  } else if (ev.key === 'ArrowUp') {
    ev.preventDefault()
    highlighted.value = Math.max(highlighted.value - 1, 0)
  } else if (ev.key === 'Enter') {
    ev.preventDefault()
    const figi = filtered.value[highlighted.value]
    if (figi) select(figi)
  }
}

/** Клик вне компонента закрывает dropdown. */
function onDocClick(ev: MouseEvent) {
  if (open.value && rootEl.value && !rootEl.value.contains(ev.target as Node)) {
    open.value = false
  }
}
document.addEventListener('mousedown', onDocClick)
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocClick))
</script>

<template>
  <div ref="rootEl" class="figi-selector">
    <button
      type="button"
      class="trigger"
      :disabled="loading || figis.length === 0"
      @click="toggle"
      @keydown="onKeydown"
    >
      <span class="trigger-label">FIGI</span>
      <span class="trigger-value">{{ modelValue || (loading ? 'Загрузка…' : 'Выберите инструмент') }}</span>
      <span class="chevron" :class="{ 'chevron--open': open }" aria-hidden="true">▾</span>
    </button>

    <div v-if="open" class="panel animate-dropdown">
      <input
        v-model="search"
        class="search"
        type="text"
        placeholder="Поиск по FIGI…"
        autofocus
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
  </div>
</template>

<style scoped>
/* Flat-стиль: тонкие линии, радиус 2px, без теней;
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

.panel {
  position: absolute;
  top: calc(100% + var(--space-xs));
  left: 0;
  right: 0;
  z-index: 30;
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
