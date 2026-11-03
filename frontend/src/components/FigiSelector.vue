<script setup lang="ts">
/**
 * FigiSelector.vue — ключевой элемент дашборда: элегантный dropdown FIGI
 * в золотой рамке на светлом фоне (брендбук).
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
      <span class="chevron" :class="{ 'chevron--open': open }">▾</span>
    </button>

    <div v-if="open" class="panel">
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
/* Элегантный dropdown в золотой рамке, светлый фон, тонкие линии, без теней. */
.figi-selector {
  position: relative;
  min-width: 240px;
}

.trigger {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: #ffffff;
  border: 1px solid var(--color-gold, #d4af37);
  border-radius: 6px;
  cursor: pointer;
  font: inherit;
  color: var(--color-text-primary, #1a1a1a);
}

.trigger:disabled {
  cursor: default;
  opacity: 0.6;
}

.trigger-label {
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--color-gold-dark, #a8871c);
}

.trigger-value {
  flex: 1;
  text-align: left;
  font-size: 14px;
  font-weight: 300;
  letter-spacing: 0.02em;
}

.chevron {
  color: var(--color-text-secondary, #6b6b6b);
  transition: transform 0.15s ease;
}

.chevron--open {
  transform: rotate(180deg);
}

.panel {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  z-index: 30;
  background: #ffffff;
  border: 1px solid var(--color-platinum-dark, #b8b7b5);
  border-top-color: var(--color-gold-light, #f4e5b8);
  border-radius: 6px;
  overflow: hidden;
}

.search {
  width: 100%;
  padding: 8px 12px;
  border: none;
  border-bottom: 1px solid var(--color-platinum, #e5e4e2);
  font: inherit;
  font-size: 13px;
  outline: none;
  background: var(--color-platinum-light, #f5f5f4);
  color: var(--color-text-primary, #1a1a1a);
}

.list {
  list-style: none;
  margin: 0;
  padding: 4px 0;
  max-height: 260px;
  overflow-y: auto;
}

.item {
  padding: 8px 14px;
  font-size: 13px;
  font-weight: 300;
  letter-spacing: 0.02em;
  cursor: pointer;
  color: var(--color-text-secondary, #6b6b6b);
}

.item:hover,
.item--highlight {
  background: var(--color-platinum-light, #f5f5f4);
  color: var(--color-gold-dark, #a8871c);
}

.item--active {
  color: var(--color-text-primary, #1a1a1a);
  border-left: 2px solid var(--color-gold, #d4af37);
  font-weight: 400;
}

.empty {
  padding: 10px 14px;
  font-size: 13px;
  color: var(--color-text-secondary, #6b6b6b);
}
</style>
