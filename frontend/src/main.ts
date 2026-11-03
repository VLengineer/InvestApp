import { createApp } from 'vue'
import App from './App.vue'
import router from './router'

// Глобальные слои стилей «Modern Platinum». Порядок важен:
// токены → reset → base → layout → animations.
// Компоненты Vue используют scoped-стили и только CSS-переменные из tokens.css.
import './styles/tokens.css'
import './styles/reset.css'
import './styles/base.css'
import './styles/layout.css'
import './styles/animations.css'

// Единственная точка монтирования: App.vue → Layout.vue → RouterView (страницы).
createApp(App).use(router).mount('#app')
