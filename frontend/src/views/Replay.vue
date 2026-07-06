<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'

const route = useRoute()
const router = useRouter()
const data = ref(null)
const error = ref('')
const loading = ref(true)

const OUTCOME = {
  planted: '进行中', found: '进行中', fixed: '已解决', internalized: '已内化',
}
const RESULT_CLASS = { OK: 'ok', RE: 'bad', WA: 'bad', HANG: 'bad' }

onMounted(async () => {
  try {
    data.value = await api.getReplay(route.params.sessionId)
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
            <pre class="code"><code>{{ s.code }}</code></pre>
          </div>
          <!-- 对话 / 运行结果 -->
          <div v-else class="msg" :class="s.role">
            <span class="who">{{ s.role === 'student' ? '你' : s.role === 'tutor' ? '导师' : '系统' }}</span>
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
.code { margin: 0; padding: 12px; background: var(--code-bg); color: var(--code-text); font-size: 12.5px; line-height: 1.55; overflow-x: auto; }
.code code { font-family: 'SF Mono', Consolas, monospace; white-space: pre; }

/* 对话气泡 */
.msg { display: flex; flex-direction: column; gap: 3px; }
.msg .who { font-size: 11.5px; color: var(--muted); }
.bubble { margin: 0; padding: 9px 13px; border-radius: 12px; font-size: 13.5px; line-height: 1.65; max-width: 90%; white-space: pre-wrap; }
.msg.student { align-items: flex-end; }
.msg.student .bubble { background: var(--accent-soft); color: var(--text); }
.msg.tutor .bubble { background: var(--panel); border: 1px solid var(--border); color: var(--text); }
.msg.system .who { color: #b08968; }
.msg.system .bubble { background: #f6efe6; color: var(--muted); font-size: 12.5px; }
</style>
