<script setup>
import { getStudentId } from './api'

const studentId = getStudentId()
</script>

<template>
  <header class="topbar">
    <div class="brand">
      <svg class="brand-mark" viewBox="0 0 48 48" aria-hidden="true">
        <defs><path id="acp-ray" d="M24 6 Q20.6 14 24 23 Q27.4 14 24 6 Z" /></defs>
        <g fill="currentColor">
          <use href="#acp-ray" />
          <use href="#acp-ray" transform="rotate(30 24 24)" />
          <use href="#acp-ray" transform="rotate(60 24 24)" />
          <use href="#acp-ray" transform="rotate(90 24 24)" />
          <use href="#acp-ray" transform="rotate(120 24 24)" />
          <use href="#acp-ray" transform="rotate(150 24 24)" />
          <use href="#acp-ray" transform="rotate(180 24 24)" />
          <use href="#acp-ray" transform="rotate(210 24 24)" />
          <use href="#acp-ray" transform="rotate(240 24 24)" />
          <use href="#acp-ray" transform="rotate(270 24 24)" />
          <use href="#acp-ray" transform="rotate(300 24 24)" />
          <use href="#acp-ray" transform="rotate(330 24 24)" />
        </g>
      </svg>
      <span>ACP Learning</span>
    </div>
    <nav>
      <RouterLink to="/arena">Bug闯关训练场</RouterLink>
      <RouterLink to="/timeline">成长轨迹</RouterLink>
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
  display: inline-flex;
  align-items: center;
  gap: 9px;
  font-family: var(--serif);
  font-weight: 600;
  font-size: 19px;
  color: var(--text);
  letter-spacing: 0.3px;
}
.brand-mark {
  width: 25px;
  height: 25px;
  color: var(--primary);
  flex-shrink: 0;
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
