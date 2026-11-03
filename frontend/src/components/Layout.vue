<script setup lang="ts">
/**
 * Layout.vue — общий лейаут приложения по брендбуку:
 *  - Header: высота 64px, платиновый фон, тонкая золотая линия снизу;
 *  - Sidebar: вертикальное меню слева (240px), золотые акценты при hover;
 *  - Content Area: <router-view /> со страницами.
 * В меню — ссылки на существующую страницу «Анализатор новостей» и новый дашборд.
 */
import { useRoute } from 'vue-router'
import { RouterLink, RouterView } from 'vue-router'

const route = useRoute()

const links = [
  { to: '/', label: 'Анализатор новостей', exact: true },
  { to: '/dashboard', label: 'Финансовый дашборд', exact: false },
]
</script>

<template>
  <div class="layout">
    <!-- ===== Header: 64px, платина, тонкая золотая линия снизу ===== -->
    <header class="header">
      <div class="logo">
        <span class="logo-mark">◆</span>
        <span class="logo-text">Финансовый терминал</span>
      </div>
      <nav class="header-nav hidden md:flex">
        <RouterLink
          v-for="link in links"
          :key="link.to"
          :to="link.to"
          class="header-link"
          :class="{ 'header-link--active': link.exact ? route.path === link.to : route.path.startsWith(link.to) }"
        >
          {{ link.label }}
        </RouterLink>
      </nav>
    </header>

    <div class="body">
      <!-- ===== Sidebar: 240px, золотые акценты при hover ===== -->
      <aside class="sidebar">
        <nav class="sidebar-nav">
          <RouterLink
            v-for="link in links"
            :key="link.to"
            :to="link.to"
            class="sidebar-link"
            :class="{ 'sidebar-link--active': link.exact ? route.path === link.to : route.path.startsWith(link.to) }"
          >
            {{ link.label }}
          </RouterLink>
        </nav>
      </aside>

      <!-- ===== Content Area: страницы через router-view ===== -->
      <main class="content">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<style scoped>
/* Минимализм: без градиентов и теней, тонкие линии, чистые карточки. */
.layout {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--color-background, #fafafa);
}

.header {
  height: 64px;
  flex: 0 0 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: var(--color-platinum-light, #f5f5f4);
  border-bottom: 1px solid var(--color-gold, #d4af37); /* тонкая золотая линия */
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 300;
  font-size: 18px;
  letter-spacing: 0.04em;
  color: var(--color-text-primary, #1a1a1a);
}

.logo-mark {
  color: var(--color-gold, #d4af37);
  font-size: 14px;
}

.header-nav {
  gap: 24px;
}

.header-link {
  font-size: 14px;
  font-weight: 300;
  text-decoration: none;
  color: var(--color-text-secondary, #6b6b6b);
  padding-bottom: 2px;
  border-bottom: 1px solid transparent;
  transition: color 0.15s ease;
}

.header-link:hover {
  color: var(--color-gold-dark, #a8871c);
}

.header-link--active {
  color: var(--color-text-primary, #1a1a1a);
  border-bottom-color: var(--color-gold, #d4af37);
}

.body {
  flex: 1;
  display: flex;
  min-height: 0;
}

.sidebar {
  width: 240px;
  flex: 0 0 240px;
  background: var(--color-platinum-light, #f5f5f4);
  border-right: 1px solid var(--color-platinum, #e5e4e2);
  padding: 24px 0;
}

.sidebar-nav {
  display: flex;
  flex-direction: column;
}

.sidebar-link {
  display: block;
  padding: 12px 24px;
  font-size: 14px;
  font-weight: 300;
  letter-spacing: 0.02em;
  text-decoration: none;
  color: var(--color-text-secondary, #6b6b6b);
  border-left: 2px solid transparent;
  transition: color 0.15s ease, border-color 0.15s ease, background-color 0.15s ease;
}

/* Золотой акцент при hover */
.sidebar-link:hover {
  color: var(--color-gold-dark, #a8871c);
  border-left-color: var(--color-gold, #d4af37);
  background: var(--color-platinum, #e5e4e2);
}

.sidebar-link--active {
  color: var(--color-text-primary, #1a1a1a);
  border-left-color: var(--color-gold, #d4af37);
  background: var(--color-gold-light, #f4e5b8);
}

.content {
  flex: 1;
  min-width: 0;
  overflow-x: auto;
}

/* Адаптивность: на узких экранах скрываем сайдбар (дашборд — от 1280px) */
@media (max-width: 1023px) {
  .sidebar {
    display: none;
  }
}
</style>
