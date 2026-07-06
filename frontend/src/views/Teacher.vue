<script setup>
// 教师端总览（M4）· 隐藏页，不挂学生导航。教师输一次 token（ACP_ADMIN_TOKEN）存本地，
// 拉全班总览渲染表格。鉴权走 ?token=，与学生身份体系解耦（不用 Bearer）。
import { onMounted, ref } from 'vue'

const TOKEN_KEY = 'acp_teacher_token'
const token = ref(localStorage.getItem(TOKEN_KEY) || '')
const inputToken = ref('')
const classId = ref('')
const data = ref(null)
const error = ref('')
const loading = ref(false)

async function load() {
  if (!token.value) return
  loading.value = true
  error.value = ''
  try {
    const q = new URLSearchParams({ token: token.value })
    if (classId.value.trim()) q.set('class_id', classId.value.trim())
    const res = await fetch('/api/teacher/overview?' + q.toString())
    if (res.status === 403) throw new Error('token 无效或未在服务器设置 ACP_ADMIN_TOKEN')
    if (!res.ok) throw new Error('加载失败 (' + res.status + ')')
    data.value = await res.json()
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
  localStorage.setItem(TOKEN_KEY, token.value)
  load()
}
function logout() {
  token.value = ''
  localStorage.removeItem(TOKEN_KEY)
  data.value = null
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

      <table v-else-if="data" class="tbl">
        <thead>
          <tr>
            <th>学号</th><th>姓名</th><th>已解决</th><th>已内化</th><th>在学</th>
            <th>最近活跃</th><th>正在进行</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in data.students" :key="r.student_id">
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

.tbl { width: 100%; border-collapse: collapse; font-size: 13.5px; }
.tbl th, .tbl td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); }
.tbl th { font-size: 12px; color: var(--muted); font-weight: 600; }
.tbl tbody tr:hover { background: var(--panel); }
.mono { font-family: 'SF Mono', Consolas, monospace; font-size: 12.5px; color: var(--muted); }
.num { text-align: center; }
.num.strong { color: var(--green); font-weight: 600; }
.cur { color: var(--muted); font-size: 12.5px; }
.foot { font-size: 12px; color: var(--muted); margin-top: 14px; }
</style>
