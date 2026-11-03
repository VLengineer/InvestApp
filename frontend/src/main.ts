import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './style.css'

// Единственная точка монтирования: App.vue → Layout.vue → RouterView (страницы).
createApp(App).use(router).mount('#app')
