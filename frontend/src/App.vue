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
  gap: 36px;
  padding: 0 32px;
  height: 64px;
  background: rgba(244, 241, 234, 0.8);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 10;
}
.brand {
  font-family: var(--serif);
  font-weight: 600;
  font-size: 19px;
  color: var(--text);
  letter-spacing: 0.3px;
}
nav { display: flex; gap: 26px; flex: 1; }
nav a {
  text-decoration: none;
  color: var(--muted);
  font-size: 14.5px;
  padding: 6px 2px;
  border-bottom: 2px solid transparent;
  transition: color 0.15s;
}
nav a:hover { color: var(--text); }
nav a.router-link-active { color: var(--primary); border-color: var(--primary); }
.student {
  font-size: 13px;
  color: var(--muted);
  background: var(--accent-soft);
  padding: 4px 12px;
  border-radius: 999px;
}
.content { flex: 1; padding: 40px 32px; max-width: 1120px; margin: 0 auto; width: 100%; }
</style>
