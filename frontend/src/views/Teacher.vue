<script setup>
// 教师端总览（M4）· 隐藏页，不挂学生导航。ACP_ADMIN_TOKEN 只存当前 sessionStorage，
// 请求统一走 Authorization Bearer，不把管理口令放进 URL / 访问日志。
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

const TOKEN_KEY = 'acp_teacher_token'
const router = useRouter()
// 教师口令只活在当前浏览器会话；不再进入 URL，也不长期留在 localStorage。
localStorage.removeItem(TOKEN_KEY)
const token = ref(sessionStorage.getItem(TOKEN_KEY) || '')
const inputToken = ref('')
const classId = ref('')
const data = ref(null)
const error = ref('')
const loading = ref(false)
const detail = ref(null)
const detailLoading = ref(false)

async function teacherFetch(path) {
  const res = await fetch('/api/teacher' + path, {
    headers: { Authorization: `Bearer ${token.value}` },
  })
  if (res.status === 403) throw new Error('token 无效或未在服务器设置 ACP_ADMIN_TOKEN')
  if (!res.ok) throw new Error(`加载失败 (${res.status})`)
  return res.json()
}

async function load() {
  if (!token.value) return
  loading.value = true
  error.value = ''
  try {
    const q = new URLSearchParams()
    if (classId.value.trim()) q.set('class_id', classId.value.trim())
    data.value = await teacherFetch('/overview' + (q.toString() ? '?' + q.toString() : ''))
    detail.value = null
  } catch (e) {
    error.value = e.message
    data.value = null
  } finally {
    loading.value = false
  }
}

function enter() {
  if (!inputToken.value.trim()) return
  token.value = inputToken.value.trim()
  sessionStorage.setItem(TOKEN_KEY, token.value)
  load()
}
function logout() {
  token.value = ''
  sessionStorage.removeItem(TOKEN_KEY)
  data.value = null
}

async function openStudent(studentId) {
  detailLoading.value = true
  error.value = ''
  try {
    detail.value = await teacherFetch(`/students/${encodeURIComponent(studentId)}`)
  } catch (e) {
    error.value = e.message
  } finally {
    detailLoading.value = false
  }
}

function openReplay(sessionId) {
  router.push(`/teacher/replay/${sessionId}`)
}

function activeText(r) {
  if (r.days_since == null) return '未开始'
  if (r.days_since <= 0) return '今天'
  return r.days_since + ' 天前'
}
function currentText(r) {
  return r.current ? `${r.current.pattern_name} · ${r.current.stage}` : '—'
}

onMounted(load)
</script>

<template>
  <div class="teacher">
    <!-- 未登录：输 token -->
    <div v-if="!token" class="gate">
      <h1>教师总览</h1>
      <p class="sub">输入访问口令查看全班学习情况（服务器 ACP_ADMIN_TOKEN）。</p>
      <input v-model="inputToken" type="password" placeholder="访问口令" @keyup.enter="enter" />
      <button :disabled="!inputToken.trim()" @click="enter">进入</button>
    </div>

    <!-- 已登录 -->
    <template v-else>
      <header class="head">
        <h1>教师总览</h1>
        <div class="tools">
          <input v-model="classId" placeholder="班级（可空=全体）" @keyup.enter="load" />
          <button @click="load">刷新</button>
          <button class="ghost" @click="logout">退出</button>
        </div>
      </header>

      <div v-if="loading" class="hint">加载中…</div>
      <div v-else-if="error" class="hint err">{{ error }}</div>
      <div v-else-if="data && !data.students.length" class="hint">还没有学生数据。</div>

      <section v-if="data?.common_stumbling_blocks?.length" class="stumbles">
        <div class="section-title">班级共性卡点</div>
        <div class="stumble-list">
          <div v-for="s in data.common_stumbling_blocks" :key="s.pattern_id + s.stage" class="stumble">
            <b>{{ s.student_count }} 人</b>
            <span>{{ s.pattern_name }}</span>
            <small>{{ s.stage }}</small>
          </div>
        </div>
      </section>

      <table v-if="data" class="tbl">
        <thead>
          <tr>
            <th>学号</th><th>姓名</th><th>已解决</th><th>已内化</th><th>在学</th>
            <th>最近活跃</th><th>正在进行</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in data.students" :key="r.student_id" class="student-row" @click="openStudent(r.student_id)">
            <td class="mono">{{ r.student_id }}</td>
            <td>{{ r.name || '—' }}</td>
            <td class="num">{{ r.solved }}</td>
            <td class="num strong">{{ r.internalized }}</td>
            <td class="num">{{ r.touched }}</td>
            <td>{{ activeText(r) }}</td>
            <td class="cur">{{ currentText(r) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="data" class="foot">共 {{ data.total }} 名学生 · 按最近活跃排序</p>

      <div v-if="detailLoading" class="hint">正在整理这名学生的过程记录…</div>
      <section v-else-if="detail" class="detail">
        <div class="detail-head">
          <div><span class="section-title">学生钻取</span><h2>{{ detail.student.name || detail.student.student_id }}</h2></div>
          <button class="ghost" @click="detail = null">关闭</button>
        </div>
        <div class="metric-row">
          <span>已解决 <b>{{ detail.progress.solved }}</b></span>
          <span>已内化 <b>{{ detail.progress.internalized }}</b></span>
          <span>困惑换路 <b>{{ detail.teaching_metrics.route_changed_turns }}</b></span>
          <span>两轮恢复率 <b>{{ detail.teaching_metrics.recovery_rate == null ? '暂无' : Math.round(detail.teaching_metrics.recovery_rate * 100) + '%' }}</b></span>
        </div>
        <div class="session-list">
          <button v-for="s in detail.sessions" :key="s.session_id" class="session-card" @click="openReplay(s.session_id)">
            <span><b>{{ s.pattern_name }}</b><small>{{ s.stage }} · {{ s.mine_status }}</small></span>
            <span class="session-action">查看过程回放 →</span>
          </button>
          <p v-if="!detail.sessions.length" class="hint">还没有可查看的学习会话。</p>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.teacher { max-width: 900px; margin: 0 auto; padding: 24px 16px 60px; }
h1 { font-family: var(--serif); font-size: 23px; color: var(--text); margin: 0; }

.gate { max-width: 360px; margin: 60px auto; text-align: center; display: flex; flex-direction: column; gap: 12px; }
.gate .sub { font-size: 13px; color: var(--muted); line-height: 1.6; margin: 4px 0 8px; }
.gate input, .tools input {
  border: 1px solid var(--border); border-radius: 8px; padding: 9px 12px; font-size: 14px;
  font-family: inherit; background: var(--panel); color: var(--text);
}
.gate button {
  background: var(--primary); color: #fff; border: none; border-radius: 999px;
  padding: 9px 18px; font-size: 14px; cursor: pointer; font-family: inherit;
}
.gate button:disabled { opacity: 0.45; cursor: not-allowed; }

.head { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }
.tools { display: flex; gap: 8px; align-items: center; }
.tools button {
  border: 1px solid var(--border); background: var(--panel); color: var(--text);
  border-radius: 999px; padding: 7px 14px; font-size: 13px; cursor: pointer; font-family: inherit;
}
.tools button:hover { border-color: var(--primary); color: var(--primary); }
.tools .ghost { color: var(--muted); }

.hint { text-align: center; color: var(--muted); margin: 50px 0; }
.hint.err { color: var(--red); }
.section-title { font-size: 12px; color: var(--muted); font-weight: 600; }
.stumbles { margin: 4px 0 20px; padding: 14px; border: 1px solid var(--border); border-radius: 12px; background: var(--panel); }
.stumble-list { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.stumble { display: grid; grid-template-columns: auto 1fr; gap: 2px 8px; min-width: 190px; padding: 8px 10px; border-radius: 9px; background: var(--accent-soft); }
.stumble b { grid-row: 1 / 3; align-self: center; color: var(--primary-dark); }
.stumble span { font-size: 12.5px; }
.stumble small { font-size: 11px; color: var(--muted); }

.tbl { width: 100%; border-collapse: collapse; font-size: 13.5px; }
.tbl th, .tbl td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); }
.tbl th { font-size: 12px; color: var(--muted); font-weight: 600; }
.tbl tbody tr:hover { background: var(--panel); }
.student-row { cursor: pointer; }
.mono { font-family: 'SF Mono', Consolas, monospace; font-size: 12.5px; color: var(--muted); }
.num { text-align: center; }
.num.strong { color: var(--green); font-weight: 600; }
.cur { color: var(--muted); font-size: 12.5px; }
.foot { font-size: 12px; color: var(--muted); margin-top: 14px; }
.detail { margin-top: 24px; padding: 18px; border: 1px solid var(--border); border-radius: 12px; background: var(--panel); }
.detail-head { display: flex; justify-content: space-between; align-items: center; }
.detail-head h2 { margin: 4px 0 0; font-family: var(--serif); font-size: 20px; }
.detail-head button { border: 0; background: none; color: var(--muted); cursor: pointer; }
.metric-row { display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0; }
.metric-row span { padding: 7px 10px; border-radius: 8px; background: var(--accent-soft); font-size: 12px; }
.session-list { display: flex; flex-direction: column; gap: 8px; }
.session-card { width: 100%; display: flex; justify-content: space-between; align-items: center; text-align: left; padding: 10px 12px; border: 1px solid var(--border); border-radius: 9px; background: #fff; color: var(--text); cursor: pointer; font-family: inherit; }
.session-card > span:first-child { display: flex; flex-direction: column; gap: 3px; }
.session-card small { color: var(--muted); }
.session-action { color: var(--primary); font-size: 12px; }
</style>
