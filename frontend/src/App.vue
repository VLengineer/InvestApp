<script setup>
import NewsAnalyzerForm from './components/NewsAnalyzerForm.vue'

const webhookUrl = import.meta.env.VITE_N8N_WEBHOOK_URL
  || 'http://n8n:5678/webhook/news_analizer'
</script>

<template>
  <main class="page">
    <header class="page-header">
      <h1>Анализатор рыночных новостей</h1>
      <p class="subtitle">
        Заполните карточку новости и нажмите «Анализировать» — JSON уйдёт
        на вебхук n8n, а сценарий n8n сохранит его в
        <code>market_news_ml_dataset</code> и проанализирует.
      </p>
      <p class="webhook">URL вебхука: <code>{{ webhookUrl }}</code></p>
    </header>

    <NewsAnalyzerForm :webhook-url="webhookUrl" />
  </main>
</template>

<style scoped>
.page {
  max-width: 720px;
  margin: 0 auto;
  padding: 32px 20px 64px;
}
.page-header h1 {
  margin: 0 0 8px;
  font-size: 28px;
}
.subtitle {
  margin: 0 0 8px;
  color: #5b6472;
}
.webhook {
  margin: 0;
  font-size: 13px;
  color: #8a93a3;
}
code {
  background: #eef1f5;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
}
</style>
