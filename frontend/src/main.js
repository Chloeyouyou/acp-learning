import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import Arena from './views/Arena.vue'
import Coop from './views/Coop.vue'
import Timeline from './views/Timeline.vue'
import Profile from './views/Profile.vue'
import QuestionTraining from './views/QuestionTraining.vue'
import Replay from './views/Replay.vue'
import Map from './views/Map.vue'
import Teacher from './views/Teacher.vue'
import './style.css'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/arena' },
    { path: '/arena', component: Arena },
    { path: '/map', component: Map },
    { path: '/coop', component: Coop },
    { path: '/question', component: QuestionTraining },
    { path: '/timeline', component: Timeline },
    { path: '/profile', component: Profile },
    { path: '/replay/:sessionId', component: Replay },
    { path: '/teacher', component: Teacher },   // 隐藏：不挂学生导航，教师直连 + 输 token
  ],
})

createApp(App).use(router).mount('#app')
