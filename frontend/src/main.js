import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import Arena from './views/Arena.vue'
import Profile from './views/Profile.vue'
import './style.css'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/arena' },
    { path: '/arena', component: Arena },
    { path: '/profile', component: Profile },
  ],
})

createApp(App).use(router).mount('#app')
