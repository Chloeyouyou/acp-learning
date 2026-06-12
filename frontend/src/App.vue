<script setup>
import { getStudentId } from './api'

const studentId = getStudentId()
</script>

<template>
  <header class="topbar">
    <div class="brand">ACP Learning</div>
    <nav>
      <RouterLink to="/arena">Bug闯关训练场</RouterLink>
      <RouterLink to="/profile">能力画像</RouterLink>
    </nav>
    <div class="student">学号 {{ studentId }}</div>
  </header>
  <main class="content">
    <RouterView />
  </main>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  gap: 32px;
  padding: 0 24px;
  height: 56px;
  background: var(--panel);
  border-bottom: 1px solid var(--border);
}
.brand { font-weight: 700; font-size: 18px; color: var(--primary); }
nav { display: flex; gap: 20px; flex: 1; }
nav a {
  text-decoration: none;
  color: var(--muted);
  padding: 4px 2px;
  border-bottom: 2px solid transparent;
}
nav a.router-link-active { color: var(--text); border-color: var(--primary); }
.student { font-size: 13px; color: var(--muted); }
.content { flex: 1; padding: 24px; max-width: 1200px; margin: 0 auto; width: 100%; }
</style>
