import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import Arena from './views/Arena.vue'
import Timeline from './views/Timeline.vue'
import Profile from './views/Profile.vue'
import QuestionTraining from './views/QuestionTraining.vue'
import './style.css'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/arena' },
    { path: '/arena', component: Arena },
    { path: '/question', component: QuestionTraining },
    { path: '/timeline', component: Timeline },
    { path: '/profile', component: Profile },
  ],
})

createApp(App).use(router).mount('#app')
