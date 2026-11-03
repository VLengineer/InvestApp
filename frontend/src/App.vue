<script setup lang="ts">
/**
 * Новый App.vue — только роутер- outlet: обе страницы (существующая и дашборд)
 * живут внутри общего Layout.vue (header + sidebar + content).
 */
import { RouterView } from 'vue-router'
</script>

<template>
  <RouterView />
</template>
