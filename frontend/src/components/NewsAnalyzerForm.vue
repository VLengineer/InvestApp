<script setup lang="ts">
/**
 * NewsAnalyzerForm.vue — форма карточки новости (переиспользуемый компонент,
 * данные принимаются через props). Стили — Modern Platinum: flat-карточка
 * с тонкой платиновой рамкой, радиусы 2px, золотые акценты на focus/hover,
 * без теней в состоянии покоя. Только CSS-переменные из tokens.css.
 */
import { reactive, ref } from 'vue'

interface Props {
  webhookUrl: string
  authToken?: string
}

const props = withDefaults(defineProps<Props>(), {
  authToken: '',
})

// Поля формы — ровно те, что уходят JSON-телом на вебхук n8n
const form = reactive({
  task_id: '',
  figi: '',
  source: '',
  title: '',
  content: '',
  ts: new Date().toISOString(), // наносекунды не нужны браузеру: ISO с ms валиден бэкендом
})

const loading = ref(false)
const error = ref('')
const result = ref(null)

async function analyze() {
  error.value = ''
  result.value = null

  if (!form.source.trim() || !form.title.trim() || !form.content.trim()) {
    error.value = 'Заполните все поля: источник, заголовок и текст новости.'
    return
  }

  const payload = {
    task_id: form.task_id.trim(),
    figi: form.figi.trim(),
    source: form.source.trim(),
    title: form.title.trim(),
    content: form.content.trim(),
    ts: form.ts,
  }

  loading.value = true
  try {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (props.authToken) {
      headers['Authorization'] = `Bearer ${props.authToken}`
    }
    const response = await fetch(props.webhookUrl, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    })
    const text = await response.text()
    let data = null
    try {
      data = JSON.parse(text)
    } catch {
      data = { raw: text }
    }
    if (!response.ok) {
      error.value = `Вебхук ответил ${response.status}: ${data?.message || data?.raw || text}`
      return
    }
    result.value = data
  } catch (e) {
    error.value = `Не удалось вызвать вебхук ${props.webhookUrl}: ${(e as Error).message}. ` +
      'ERR_NAME_NOT_RESOLVED означает, что браузер пытался открыть docker-имя (n8n) — ' +
      'обновите страницу: вызов должен идти через /n8n-api/… (прокси Vite). ' +
      'Для /webhook-test сначала нажмите «Execute workflow» в n8n, ' +
      'для /webhook включите переключатель Active.'
  } finally {
    loading.value = false
  }
}

function refreshTs() {
  form.ts = new Date().toISOString()
}
</script>

<template>
  <form class="card pl-card" @submit.prevent="analyze">
    <div class="field">
      <label for="task_id">task_id</label>
      <input id="task_id" v-model="form.task_id" type="text" placeholder="например: SBER" />
    </div>

    <div class="field">
      <label for="figi">FIGI</label>
      <input id="figi" v-model="form.figi" type="text" placeholder="например: SBER" />
    </div>

    <div class="field">
      <label for="source">Источник</label>
      <input id="source" v-model="form.source" type="text" placeholder="например: Reuters" />
    </div>

    <div class="field">
      <label for="title">Заголовок</label>
      <input id="title" v-model="form.title" type="text" placeholder="Заголовок новости" />
    </div>

    <div class="field">
      <label for="content">Текст новости</label>
      <textarea id="content" v-model="form.content" rows="6" placeholder="Полный текст новости…" />
    </div>

    <div class="field">
      <label for="ts">Время публикации (ts)</label>
      <div class="ts-row">
        <input id="ts" v-model="form.ts" type="text" class="mono" />
        <button type="button" class="btn btn--ghost" @click="refreshTs">Сейчас</button>
      </div>
    </div>

    <button class="btn btn--primary" type="submit" :disabled="loading">
      {{ loading ? 'Анализируем…' : 'Анализировать' }}
      <span v-if="!loading" class="btn-arrow" aria-hidden="true">→</span>
    </button>

    <p v-if="error" class="status status--error">{{ error }}</p>

    <div v-if="result" class="status status--success">
      <p>Новость принята и сохранена.</p>
      <pre>{{ JSON.stringify(result, null, 2) }}</pre>
    </div>
  </form>
</template>

<style scoped>
.card {
  margin-top: var(--space-md);
}

/* ---------- Поля ---------- */
.field {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  margin-bottom: var(--space-sm);
}

label {
  font-size: var(--fs-micro);
  font-weight: var(--fw-medium);
  letter-spacing: var(--ls-wide);
  text-transform: uppercase;
  color: var(--color-grey-light);
}

input,
textarea {
  padding: 10px var(--space-sm);
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-platinum);
  border-radius: var(--radius-sm);
  font-size: var(--fs-small);
  font-weight: var(--fw-light);
  color: var(--color-ink);
  transition:
    border-color var(--duration-fast) var(--ease-out),
    box-shadow var(--duration-fast) var(--ease-out);
}

input::placeholder,
textarea::placeholder {
  color: var(--color-grey-light);
}

input:hover,
textarea:hover {
  border-color: var(--color-platinum-dark);
}

/* Focus — точечный золотой акцент вместо синего */
input:focus,
textarea:focus {
  outline: none;
  border-color: var(--color-gold);
  box-shadow: 0 0 0 3px var(--color-gold-soft);
}

.mono {
  font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
  font-size: var(--fs-micro);
}

.ts-row {
  display: flex;
  gap: var(--space-xs);
}

.ts-row input {
  flex: 1;
}

/* ---------- Кнопки: без тени в покое ---------- */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-xs);
  padding: 12px var(--space-md);
  border-radius: var(--radius-sm);
  font-size: var(--fs-small);
  font-weight: var(--fw-medium);
  letter-spacing: var(--ls-tight);
  cursor: pointer;
  transition:
    background-color var(--duration-fast) var(--ease-out),
    color var(--duration-fast) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out);
}

.btn--primary {
  width: 100%;
  background: var(--color-gold);
  color: var(--color-bg-elevated);
}

.btn--primary:hover:not(:disabled) {
  background: var(--color-gold-hover);
}

/* Стрелка — лёгкий translateX на hover */
.btn-arrow {
  transition: transform var(--duration-fast) var(--ease-out);
}

.btn--primary:hover:not(:disabled) .btn-arrow {
  transform: translateX(4px);
}

.btn--primary:disabled {
  opacity: 0.6;
  cursor: progress;
}

.btn--ghost {
  background: var(--color-bg-elevated);
  color: var(--color-ink-soft);
  border: 1px solid var(--color-platinum);
}

.btn--ghost:hover {
  border-color: var(--color-gold);
  color: var(--color-gold-hover);
}

/* ---------- Статусы ---------- */
.status {
  margin-top: var(--space-sm);
  padding: var(--space-sm);
  border-radius: var(--radius-sm);
  font-size: var(--fs-small);
  font-weight: var(--fw-light);
  line-height: var(--lh-normal);
}

.status--error {
  border: 1px solid var(--color-platinum-dark);
  border-left: 2px solid var(--color-ink);
  color: var(--color-ink);
  background: var(--color-platinum-soft);
}

.status--success {
  border: 1px solid var(--color-platinum);
  border-left: 2px solid var(--color-gold);
  color: var(--color-ink-soft);
  background: var(--color-gold-soft);
}

.status--success pre {
  margin-top: var(--space-xs);
  background: var(--color-bg-elevated);
  border: 1px solid var(--color-platinum);
  border-radius: var(--radius-sm);
  padding: var(--space-xs);
  overflow: auto;
  font-size: var(--fs-micro);
}
</style>
