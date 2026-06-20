<script setup>
import { ref } from 'vue'
import {
  clearIdentityChoice, getLegacyId, getStudentId, getStudentName,
  hasIdentity, keepLegacyIdentity, setIdentity,
} from './api'

const ready = ref(hasIdentity())          // 已确立身份才渲染应用，否则弹身份页
const studentId = ref(getStudentId())
const studentName = ref(getStudentName())
const legacyId = ref(getLegacyId())        // 本设备旧随机 id（迁移候选），新访客为 ''

const formId = ref('')
const formName = ref('')

function confirmIdentity() {
  const id = formId.value.trim()
  if (!id) return
  setIdentity(id, formName.value.trim())
  location.reload()  // 重载，让接着做/复习/画像等所有页面按新 student_id 重新取数
}

function useLegacy() {
  keepLegacyIdentity(formName.value.trim())
  location.reload()
}

function switchIdentity() {
  clearIdentityChoice()          // 撤销「已选」，旧 id 成为迁移候选
  legacyId.value = getLegacyId()
  formId.value = ''
  formName.value = ''
  ready.value = false
}
</script>

<template>
  <template v-if="ready">
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
      <button class="student" @click="switchIdentity" title="切换身份">
        当前：{{ studentId }}<template v-if="studentName"> / {{ studentName }}</template>
      </button>
    </header>
    <main class="content">
      <RouterView />
    </main>
  </template>

  <!-- 轻量身份页：没确立身份时盖住全站；无密码、无后端鉴权 -->
  <div v-else class="identity-gate">
    <div class="identity-card">
      <div class="identity-brand">ACP Learning</div>
      <h1 class="identity-title">先填一下你的身份</h1>
      <p class="identity-sub">用学号记住你——换设备、清缓存后，输同一个学号就能找回你的进度、接着做和复习。</p>

      <label class="identity-field">
        <span>学号</span>
        <input v-model="formId" placeholder="例如 2025xxxxxx" @keyup.enter="confirmIdentity" />
      </label>
      <label class="identity-field">
        <span>姓名（可选）</span>
        <input v-model="formName" placeholder="昵称也行" @keyup.enter="confirmIdentity" />
      </label>
      <button class="identity-go" :disabled="!formId.trim()" @click="confirmIdentity">进入</button>

      <div v-if="legacyId" class="identity-legacy">
        <p>这台设备上已有一份学习记录（{{ legacyId }}）。</p>
        <button class="identity-legacy-btn" @click="useLegacy">继续沿用这份记录</button>
      </div>
    </div>
  </div>
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
  border: 1px solid transparent;
  cursor: pointer;
  font-family: inherit;
  transition: border-color 0.15s, color 0.15s;
}
.student:hover { color: var(--text); border-color: #dac9b8; }
.content { flex: 1; padding: 40px 32px; max-width: 1120px; margin: 0 auto; width: 100%; }

/* 轻量身份页 */
.identity-gate {
  min-height: 100vh; display: flex; align-items: center; justify-content: center;
  padding: 24px; background: var(--bg, #f4f1ea);
}
.identity-card {
  width: 100%; max-width: 420px; background: var(--panel); border: 1px solid var(--border);
  border-radius: 18px; padding: 36px 32px; box-shadow: 0 24px 60px -30px rgba(43, 41, 36, 0.35);
}
.identity-brand {
  font-family: var(--serif); font-weight: 600; font-size: 18px; color: var(--primary);
  letter-spacing: 0.3px; margin-bottom: 20px;
}
.identity-title { font-family: var(--serif); font-size: 22px; font-weight: 600; color: var(--text); margin: 0 0 8px; }
.identity-sub { font-size: 13.5px; color: var(--muted); line-height: 1.7; margin: 0 0 22px; }
.identity-field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
.identity-field span { font-size: 13px; color: var(--text); }
.identity-field input {
  font-size: 15px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 10px;
  background: #fff; color: var(--text); font-family: inherit; outline: none;
}
.identity-field input:focus { border-color: var(--primary); }
.identity-go {
  width: 100%; margin-top: 8px; padding: 11px; border: none; border-radius: 10px; cursor: pointer;
  background: var(--primary); color: #fff; font-family: var(--serif); font-size: 15px; font-weight: 600;
  transition: opacity 0.15s;
}
.identity-go:disabled { opacity: 0.45; cursor: not-allowed; }
.identity-legacy { margin-top: 22px; padding-top: 18px; border-top: 1px solid var(--border); }
.identity-legacy p { font-size: 13px; color: var(--muted); margin: 0 0 10px; line-height: 1.6; }
.identity-legacy-btn {
  border: 1px solid #dac9b8; background: var(--accent-soft); color: var(--text); cursor: pointer;
  font-size: 13.5px; font-family: inherit; padding: 8px 16px; border-radius: 999px;
}
.identity-legacy-btn:hover { border-color: var(--primary); color: var(--primary); }

/* 手机端：顶栏收紧、隐藏学号、内容留白变小 */
@media (max-width: 640px) {
  .topbar { gap: 12px; padding: 0 14px; height: 54px; }
  .brand { font-size: 16px; gap: 7px; }
  .brand-mark { width: 22px; height: 22px; }
  nav { gap: 14px; }
  nav a { font-size: 13px; padding: 6px 0; }
  .student { display: none; }
  .content { padding: 18px 12px; }
}
</style>
