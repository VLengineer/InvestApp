<script setup lang="ts">
/**
 * Layout.vue — общий лейаут приложения в стиле «Modern Platinum»:
 *  - Header: 64px, белый/платиновый, тонкая золотая линия снизу;
 *  - Sidebar: вертикальное меню слева (240px), золотой акцент при hover;
 *  - Content Area: <RouterView /> со страницами.
 * Каркас (шапки, сайдбар, контейнеры) описан глобальными классами из
 * styles/layout.css; здесь — только scoped-стили навигации на токенах.
 */
import { useRoute } from 'vue-router'
import { RouterLink, RouterView } from 'vue-router'

const route = useRoute()

const links = [
  { to: '/', label: 'Анализатор новостей', exact: true },
  { to: '/dashboard', label: 'Финансовый дашборд', exact: false },
]

function isActive(link: { to: string; exact: boolean }) {
  return link.exact ? route.path === link.to : route.path.startsWith(link.to)
}
</script>

<template>
  <div class="app-layout">
    <!-- ===== Header: 64px, платина, тонкая золотая линия снизу ===== -->
    <header class="app-header">
      <div class="app-logo">
        <span class="logo-mark" aria-hidden="true">◆</span>
        <span class="logo-text">Финансовый терминал</span>
      </div>
      <nav class="header-nav" aria-label="Основная навигация">
        <RouterLink
          v-for="link in links"
          :key="link.to"
          :to="link.to"
          class="header-link"
          :class="{ 'header-link--active': isActive(link) }"
        >
          {{ link.label }}
        </RouterLink>
      </nav>
    </header>

    <div class="app-body">
      <!-- ===== Sidebar: 240px, золотые акценты при hover ===== -->
      <aside class="app-sidebar">
        <nav class="sidebar-nav" aria-label="Меню разделов">
          <RouterLink
            v-for="link in links"
            :key="link.to"
            :to="link.to"
            class="sidebar-link"
            :class="{ 'sidebar-link--active': isActive(link) }"
          >
            {{ link.label }}
          </RouterLink>
        </nav>
      </aside>

      <!-- ===== Content Area: страницы через router-view ===== -->
      <main class="app-content">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<style scoped>
/* Навигация: underline-анимация ссылок (точечный золотой акцент),
   всё — через токены, без хардкод-цветов. */
.header-nav {
  display: flex;
  align-items: center;
  gap: var(--space-md);
}

.header-link {
  position: relative;
  font-size: var(--fs-small);
  font-weight: var(--fw-light);
  letter-spacing: var(--ls-tight);
  color: var(--color-grey);
  padding: var(--space-xs) 0;
  transition: color var(--duration-fast) var(--ease-out);
}

/* Hover-эффект: тонкая золотая линия снизу */
.header-link::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 1px;
  background: var(--color-gold);
  transform: scaleX(0);
  transform-origin: left;
  transition: transform var(--duration-fast) var(--ease-out);
}

.header-link:hover {
  color: var(--color-ink);
}

.header-link:hover::after {
  transform: scaleX(1);
}

.header-link--active {
  color: var(--color-ink);
  font-weight: var(--fw-medium);
}

.header-link--active::after {
  transform: scaleX(1);
}

.sidebar-nav {
  display: flex;
  flex-direction: column;
}

.sidebar-link {
  display: block;
  padding: var(--space-sm) var(--space-md);
  font-size: var(--fs-small);
  font-weight: var(--fw-light);
  letter-spacing: var(--ls-tight);
  color: var(--color-grey);
  border-left: 2px solid transparent;
  transition:
    color var(--duration-fast) var(--ease-out),
    border-color var(--duration-fast) var(--ease-out),
    background-color var(--duration-fast) var(--ease-out),
    padding-left var(--duration-fast) var(--ease-out);
}

/* Золотой акцент при hover + лёгкий сдвиг вправо */
.sidebar-link:hover {
  color: var(--color-ink);
  border-left-color: var(--color-gold);
  background: var(--color-gold-soft);
  padding-left: calc(var(--space-md) + var(--space-xs));
}

.sidebar-link--active {
  color: var(--color-ink);
  font-weight: var(--fw-medium);
  border-left-color: var(--color-gold);
  background: var(--color-bg-elevated);
}

/* Адаптив: на узких экранах скрываем верхнее меню и сайдбар
   (каркас .app-sidebar скрыт в layout.css). */
@media (max-width: 1023px) {
  .header-nav {
    gap: var(--space-sm);
  }
}

@media (max-width: 640px) {
  .header-nav {
    display: none;
  }
}
</style>
