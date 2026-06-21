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
    <div class="app-page">
      <div class="app-card">
        <header class="topbar">
          <div class="brand"><span class="brand-logo">知</span> ACP Learning</div>
          <nav>
            <RouterLink to="/arena">Bug 闯关</RouterLink>
            <RouterLink to="/timeline">成长轨迹</RouterLink>
            <RouterLink to="/profile">能力画像</RouterLink>
          </nav>
          <span class="topbar-id">{{ studentId }}<template v-if="studentName"> · {{ studentName }}</template></span>
          <button class="topbar-switch" @click="switchIdentity" title="切换身份">切换身份</button>
        </header>
        <main class="content">
          <RouterView />
        </main>
      </div>
    </div>
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
/* 共用外壳（设计稿）：暖象牙底 + 居中圆角卡 + 浅色顶栏 */
.app-page {
  min-height: 100vh; padding: 28px; box-sizing: border-box;
  background: radial-gradient(1100px 560px at 88% -12%, #efe6d6 0%, rgba(239,230,214,0) 58%), #f4f1ea;
}
.app-card {
  max-width: 1480px; margin: 0 auto; display: flex; flex-direction: column;
  background: #fcfbf7; border: 1px solid #e7e2d6; border-radius: 14px; overflow: hidden;
  box-shadow: 0 24px 60px -34px rgba(43, 41, 36, 0.35);
}
.topbar { display: flex; align-items: center; gap: 26px; height: 60px; padding: 0 24px; background: #fcfbf7; border-bottom: 1px solid #ece5d8; }
.brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 16px; color: #2b2924; }
.brand-logo { width: 24px; height: 24px; border-radius: 7px; background: #c15f3c; color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; flex-shrink: 0; }
nav { display: flex; gap: 22px; flex: 1; font-size: 14px; }
nav a { text-decoration: none; color: #8a8275; transition: color 0.15s; }
nav a:hover { color: #2b2924; }
nav a.router-link-active { color: #2b2924; font-weight: 600; }
.topbar-id { font-family: 'IBM Plex Mono', monospace; font-size: 12.5px; color: #8a8275; background: #f4efe5; border: 1px solid #e7e2d6; padding: 6px 13px; border-radius: 7px; }
.topbar-switch { font-size: 13px; color: #6f695d; background: #fff; border: 1px solid #e7e2d6; padding: 7px 14px; border-radius: 8px; cursor: pointer; }
.topbar-switch:hover { border-color: #c15f3c; color: #c15f3c; }
.content { flex: 1; padding: 28px 30px; background: #faf7f0; }

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
  .app-page { padding: 12px; }
  .topbar { gap: 12px; padding: 0 14px; height: 54px; }
  .brand { font-size: 15px; gap: 7px; }
  nav { gap: 14px; }
  nav a { font-size: 13px; }
  .topbar-id, .topbar-switch { display: none; }
  .content { padding: 16px 14px; }
}
</style>
