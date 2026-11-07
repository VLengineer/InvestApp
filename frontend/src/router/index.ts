/**
 * Роутер Vue 3. Оба view подключены к общему лейауту Layout.vue:
 *  /            — существующая страница «Анализатор новостей» (без изменений);
 *  /dashboard   — новый финансовый дашборд (FIGI-селектор + графики + real-time).
 */

import { createRouter, createWebHistory } from 'vue-router'
import Layout from '../components/Layout.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: Layout,
      children: [
        {
          path: '',
          name: 'news-analyzer',
          // lazy-загрузка: не тянем echarts/lightweight-charts на страницу анализатора
          component: () => import('../views/NewsAnalyzer.vue'),
          meta: { title: 'Анализатор новостей' },
        },
        {
          path: 'dashboard',
          name: 'dashboard',
          component: () => import('../views/Dashboard.vue'),
          meta: { title: 'Финансовый дашборд' },
        },
        {
          path: 'all-news',
          name: 'all-news',
          component: () => import('../views/AllNewsView.vue'),
          meta: { title: 'Аналитика новостей' },
        },
      ],
    },
  ],
})

router.afterEach((to) => {
  const title = (to.meta?.title as string) || ''
  document.title = title ? `${title} — Финансовый терминал` : 'Финансовый терминал'
})

export default router
