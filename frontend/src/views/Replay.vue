<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'

const route = useRoute()
const router = useRouter()
const data = ref(null)
const error = ref('')
const loading = ref(true)
const teacherMode = computed(() => route.meta.teacher === true)

const OUTCOME = {
  planted: '进行中', found: '进行中', fixed: '已解决', internalized: '已内化',
}
const RESULT_CLASS = { OK: 'ok', RE: 'bad', WA: 'bad', HANG: 'bad' }

onMounted(async () => {
  try {
    if (teacherMode.value) {
      const token = sessionStorage.getItem('acp_teacher_token') || ''
      if (!token) throw new Error('教师访问口令已失效，请返回教师总览重新进入')
      const res = await fetch(`/api/teacher/sessions/${route.params.sessionId}/replay`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error(res.status === 403 ? '教师访问口令无效' : `请求失败 (${res.status})`)
      data.value = await res.json()
    } else {
      data.value = await api.getReplay(route.params.sessionId)
    }
  } catch (e) {
    error.value = '加载失败：' + e.message
  } finally {
    loading.value = false
  }
})

// 代码步给一个「第几版」序号 + diff 大白话
function diffNote(d) {
  if (!d) return ''
  const parts = []
  if (d.lines_changed != null) parts.push(`改了 ${d.lines_changed} 行`)
  if (d.touched_mine_line === true) parts.push('动了关键那一行')
  else if (d.touched_mine_line === false) parts.push('没动关键行')
  return parts.join(' · ')
}

const codeCount = computed(() => data.value?.code_versions || 0)

const PURPOSE = {
  debug_observation: '观察真实运行结果',
  verify_hypothesis: '验证调试假设',
  collaborative_debug: '协作调试',
  judge_submission: '提交判定',
}
const ROUTE = {
  skeleton: '整体骨架', analogy: '生活化比喻', micro_example: '极小例子',
  execution_trace: '执行链', contrast: '对照解释',
}

function actionNote(ctx) {
  if (!ctx) return ''
  return `${PURPOSE[ctx.purpose] || ctx.purpose} · 风险 L${ctx.risk_level ?? '?'} · ${ctx.execution === 'completed' ? '已执行' : (ctx.execution || '待执行')}`
}

function teachingNote(step) {
  const strategy = step.meta?.teaching_strategy
  if (!strategy?.route_changed) return ''
  const gap = strategy.knowledge_gap ? `，先补“${strategy.knowledge_gap}”` : ''
  return `知返发现原来的讲法没接住，改用${ROUTE[strategy.explanation_route] || '另一条路线'}${gap}`
}

// 系统运行结果消息：去掉前缀，正文更干净
function cleanContent(m) {
  return (m.content || '').replace(/^（系统·运行结果）/, '').replace(/^（系统：?/, '').replace(/）$/, '')
}
</script>

<template>
  <div class="replay">
    <button class="back" @click="router.back()">← 返回</button>

    <div v-if="loading" class="hint">加载回放中…</div>
    <div v-else-if="error" class="hint err">{{ error }}</div>
    <div v-else-if="!data || !data.steps.length" class="hint">
      这道题还没有可回放的过程记录（先去做一遍、跑一跑、聊一聊就有了）。
    </div>

    <template v-else>
      <header class="head">
        <h1>{{ data.pattern_name }}</h1>
        <div class="meta">
          <span class="outcome" :class="data.mine_status">{{ OUTCOME[data.mine_status] || '进行中' }}</span>
          <span class="vers">共 {{ codeCount }} 版代码</span>
        </div>
        <p class="lead">回看你是怎么一步步想通这道题的——每一次运行、每一版改动、每一句对话。</p>
        <div v-if="data.turning_points?.length" class="turn-summary">
          <b>这次过程里有 {{ data.turning_points.length }} 个值得记住的转折</b>
          <span>{{ data.turning_points.map(x => x.title).join(' · ') }}</span>
        </div>
      </header>

      <ol class="timeline">
        <li v-for="(s, i) in data.steps" :key="i" :class="['step', s.kind]">
          <!-- 代码版本 -->
          <div v-if="s.kind === 'code'" class="code-step">
            <div class="code-head">
              <span class="badge">第 {{ s.version }} 版</span>
              <span class="src">{{ s.source === 'submit' ? '提交' : '运行' }}</span>
              <span v-if="s.result_label" class="res" :class="RESULT_CLASS[s.result]">{{ s.result_label }}</span>
              <span v-if="diffNote(s.diff_stats)" class="diff">{{ diffNote(s.diff_stats) }}</span>
            </div>
            <div v-if="s.annotations?.length" class="annotations">
              <div v-for="a in s.annotations" :key="a.type" :class="['annotation', a.type]">
                <b>{{ a.type === 'breakthrough' ? '💡 ' : '↗ ' }}{{ a.title }}</b>
                <span>{{ a.detail }}</span>
              </div>
            </div>
            <div v-if="actionNote(s.action_context)" class="action-note" :title="s.action_context.call_id">
              <span>动作证据</span>{{ actionNote(s.action_context) }}
              <code>{{ s.action_context.call_id }}</code>
            </div>
            <pre class="code"><code>{{ s.code }}</code></pre>
          </div>
          <!-- 对话 / 运行结果 -->
          <div v-else class="msg" :class="s.role">
            <span class="who">{{ s.role === 'student' ? '你' : s.role === 'tutor' ? '导师' : '系统' }}</span>
            <span v-if="teachingNote(s)" class="teaching-note">{{ teachingNote(s) }}</span>
            <p class="bubble">{{ cleanContent(s) }}</p>
          </div>
        </li>
      </ol>
    </template>
  </div>
</template>

<style scoped>
.replay { max-width: 760px; margin: 0 auto; padding: 20px 16px 60px; }
.back {
  background: none; border: 1px solid var(--border); color: var(--muted);
  border-radius: 999px; padding: 6px 14px; font-size: 13px; cursor: pointer; font-family: inherit;
}
.back:hover { border-color: var(--primary); color: var(--primary); }
.hint { text-align: center; color: var(--muted); margin: 60px 0; font-size: 14px; }
.hint.err { color: var(--red); }

.head { margin: 22px 0 8px; }
.head h1 { font-family: var(--serif); font-size: 24px; color: var(--text); margin: 0 0 10px; }
.meta { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; }
.outcome { font-size: 12px; padding: 3px 10px; border-radius: 999px; background: var(--accent-soft); color: var(--primary-dark); }
.outcome.internalized { background: #dfe8d8; color: var(--green); }
.vers { font-size: 12px; color: var(--muted); }
.lead { font-size: 13.5px; color: var(--muted); line-height: 1.7; margin: 0; }
.turn-summary { margin-top: 14px; padding: 11px 13px; border-radius: 10px; background: #f6efe6; display: flex; flex-direction: column; gap: 4px; }
.turn-summary b { font-size: 12.5px; color: #7b5e42; }
.turn-summary span { font-size: 12px; color: var(--muted); }

.timeline { list-style: none; padding: 0; margin: 24px 0 0; border-left: 2px solid var(--border); }
.step { position: relative; padding: 0 0 20px 22px; }
.step::before {
  content: ''; position: absolute; left: -7px; top: 4px; width: 12px; height: 12px;
  border-radius: 50%; background: var(--panel); border: 2px solid var(--border);
}
.step.code::before { border-color: var(--primary); }

/* 代码版本卡 */
.code-step { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.code-head { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 9px 12px; border-bottom: 1px solid var(--border); }
.badge { font-size: 12px; font-weight: 600; color: var(--primary-dark); }
.src { font-size: 12px; color: var(--muted); }
.res { font-size: 11px; padding: 2px 8px; border-radius: 999px; }
.res.ok { background: #dfe8d8; color: var(--green); }
.res.bad { background: #f3ded7; color: var(--red); }
.diff { font-size: 11.5px; color: var(--muted); margin-left: auto; }
.annotations { padding: 10px 12px 0; display: flex; flex-direction: column; gap: 7px; }
.annotation { padding: 8px 10px; border-left: 3px solid #b9a98f; background: #f8f5ed; display: flex; flex-direction: column; gap: 2px; }
.annotation.breakthrough { border-left-color: var(--green); background: #eef4e9; }
.annotation b { font-size: 12.5px; color: var(--text); }
.annotation span { font-size: 12px; line-height: 1.55; color: var(--muted); }
.action-note { margin: 10px 12px 0; font-size: 11px; color: var(--muted); display: flex; gap: 7px; flex-wrap: wrap; align-items: center; }
.action-note > span { color: var(--primary-dark); font-weight: 600; }
.action-note code { font-size: 10.5px; color: #9a8b76; }
.code { margin: 0; padding: 12px; background: var(--code-bg); color: var(--code-text); font-size: 12.5px; line-height: 1.55; overflow-x: auto; }
.code code { font-family: 'SF Mono', Consolas, monospace; white-space: pre; }

/* 对话气泡 */
.msg { display: flex; flex-direction: column; gap: 3px; }
.msg .who { font-size: 11.5px; color: var(--muted); }
.teaching-note { font-size: 11px; color: #8b704c; background: #f6efe6; padding: 4px 8px; border-radius: 8px; max-width: 90%; }
.bubble { margin: 0; padding: 9px 13px; border-radius: 12px; font-size: 13.5px; line-height: 1.65; max-width: 90%; white-space: pre-wrap; }
.msg.student { align-items: flex-end; }
.msg.student .bubble { background: var(--accent-soft); color: var(--text); }
.msg.tutor .bubble { background: var(--panel); border: 1px solid var(--border); color: var(--text); }
.msg.system .who { color: #b08968; }
.msg.system .bubble { background: #f6efe6; color: var(--muted); font-size: 12.5px; }
</style>
