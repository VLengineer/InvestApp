<script setup>
import { reactive, ref } from 'vue'

const props = defineProps({
  webhookUrl: { type: String, required: true },
})

// Поля формы — ровно те, что уходят JSON-телом на вебхук n8n
const form = reactive({
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
    source: form.source.trim(),
    title: form.title.trim(),
    content: form.content.trim(),
    ts: form.ts,
  }

  loading.value = true
  try {
    const response = await fetch(props.webhookUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
    error.value = `Не удалось вызвать вебхук ${props.webhookUrl}: ${e.message}. ` +
      'Проверьте, что контейнеры n8n и frontend в одной сети app_net ' +
      'и что webhook news_analizer активен в n8n.'
  } finally {
    loading.value = false
  }
}

function refreshTs() {
  form.ts = new Date().toISOString()
}
</script>

<template>
  <form class="card" @submit.prevent="analyze">
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
        <input id="ts" v-model="form.ts" type="text" />
        <button type="button" class="secondary" @click="refreshTs">Сейчас</button>
      </div>
    </div>

    <button class="primary" type="submit" :disabled="loading">
      {{ loading ? 'Анализируем…' : 'Анализировать' }}
    </button>

    <p v-if="error" class="status error">{{ error }}</p>

    <div v-if="result" class="status success">
      <p>✅ Новость отправлена на вебхук.</p>
      <pre>{{ JSON.stringify(result, null, 2) }}</pre>
    </div>
  </form>
</template>

<style scoped>
.card {
  margin-top: 24px;
  padding: 24px;
  border: 1px solid #dfe3ea;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.06);
}
.field {
  margin-bottom: 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
label {
  font-weight: 600;
  font-size: 14px;
  color: #303846;
}
input,
textarea {
  font: inherit;
  padding: 10px 12px;
  border: 1px solid #c7ced9;
  border-radius: 8px;
  outline: none;
}
input:focus,
textarea:focus {
  border-color: #4f7cff;
  box-shadow: 0 0 0 3px rgba(79, 124, 255, 0.15);
}
.ts-row {
  display: flex;
  gap: 8px;
}
.ts-row input {
  flex: 1;
  font-family: monospace;
}
button {
  font: inherit;
  cursor: pointer;
  border: none;
  border-radius: 8px;
  padding: 10px 18px;
}
.primary {
  width: 100%;
  background: #4f7cff;
  color: #fff;
  font-weight: 600;
}
.primary:disabled {
  opacity: 0.6;
  cursor: progress;
}
.secondary {
  background: #eef1f5;
  color: #303846;
}
.status {
  margin-top: 16px;
  padding: 12px;
  border-radius: 8px;
  font-size: 14px;
}
.error {
  background: #fdecec;
  color: #b3261e;
}
.success {
  background: #eaf7ee;
  color: #14682d;
}
.success pre {
  background: #fff;
  padding: 10px;
  border-radius: 6px;
  overflow: auto;
  font-size: 12px;
}
</style>
