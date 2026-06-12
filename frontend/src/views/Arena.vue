<script setup>
import { onMounted, reactive, ref, nextTick } from 'vue'
import { api } from '../api'

const STAGES = ['①发现', '②定位', '③归因', '④修复', '⑤验证', '⑥内化']

const patterns = ref([])
const session = reactive({
  id: null, code: '', task: '', stage: '①发现', hintLevel: 'L0',
  completed: false, internalizeQuestions: [],
})
const messages = ref([]) // {role: 'student'|'tutor'|'system', text}
const draft = ref('')
const sending = ref(false)
const submitting = ref(false)
const error = ref('')
const chatBox = ref(null)

onMounted(async () => {
  try {
    patterns.value = await api.listPatterns()
  } catch (e) {
    error.value = '无法连接后端：' + e.message
  }
})

async function start(patternId) {
  error.value = ''
  try {
    const data = await api.createSession(patternId)
    session.id = data.session_id
    session.code = data.code
    session.task = data.task
    session.stage = '①发现'
    session.hintLevel = 'L0'
    session.completed = false
    session.internalizeQuestions = []
    messages.value = [{ role: 'system', text: data.task }]
  } catch (e) {
    error.value = e.message
  }
}

async function scrollChat() {
  await nextTick()
  if (chatBox.value) chatBox.value.scrollTop = chatBox.value.scrollHeight
}

async function send() {
  const text = draft.value.trim()
  if (!text || sending.value) return
  draft.value = ''
  messages.value.push({ role: 'student', text })
  sending.value = true
  scrollChat()
  try {
    const d = await api.sendMessage(session.id, text)
    messages.value.push({ role: 'tutor', text: d.reply })
    session.stage = d.stage
    session.hintLevel = d.hint_level
  } catch (e) {
    messages.value.push({ role: 'system', text: '出错了：' + e.message })
  } finally {
    sending.value = false
    scrollChat()
  }
}

async function submit() {
  if (submitting.value) return
  submitting.value = true
  try {
    const d = await api.submitFix(session.id, session.code)
    if (d.passed) {
      session.completed = true
      session.stage = '⑥内化'
      session.internalizeQuestions = d.internalize_questions || []
      messages.value.push({ role: 'system', text: d.message })
    } else {
      messages.value.push({ role: 'system', text: d.message })
    }
  } catch (e) {
    messages.value.push({ role: 'system', text: '提交失败：' + e.message })
  } finally {
    submitting.value = false
    scrollChat()
  }
}

function quit() {
  session.id = null
  messages.value = []
}
</script>

<template>
  <div v-if="error" class="panel error">{{ error }}</div>

  <!-- 选题 -->
  <div v-if="!session.id">
    <h2>选择一个关卡</h2>
    <p class="hint">每一关的代码里都藏着一个真实Bug。你的任务：发现它、和AI导师一起定位它、自己修好它。</p>
    <div class="cards">
      <div v-for="p in patterns" :key="p.id" class="panel card">
        <div class="card-head">
          <span class="tag">{{ p.category }}</span>
          <span class="tag difficulty">{{ p.difficulty }}</span>
        </div>
        <h3>{{ p.name }}</h3>
        <div class="card-id">{{ p.id }}</div>
        <button class="primary" @click="start(p.id)">开始挑战</button>
      </div>
    </div>
  </div>

  <!-- 做题 -->
  <div v-else class="workspace">
    <div class="stage-bar panel">
      <span
        v-for="s in STAGES" :key="s"
        :class="['stage', { active: s === session.stage, done: STAGES.indexOf(s) < STAGES.indexOf(session.stage) }]"
      >{{ s }}</span>
      <span class="spacer" />
      <span class="hint-level">提示级别 {{ session.hintLevel }}</span>
      <button @click="quit">退出关卡</button>
    </div>

    <div class="cols">
      <div class="panel code-panel">
        <div class="panel-title">
          代码（直接在这里修改）
          <button class="primary" :disabled="submitting || session.completed" @click="submit">
            {{ submitting ? '判定中…' : '提交修复' }}
          </button>
        </div>
        <textarea v-model="session.code" class="code" spellcheck="false" :disabled="session.completed" />
        <div v-if="session.completed" class="success">
          ✅ 已通过！该知识点现在是「已解决」——想升级为「已内化」，先回答下面的问题（向导师发送你的回答）：
          <ol>
            <li v-for="q in session.internalizeQuestions" :key="q">{{ q }}</li>
          </ol>
        </div>
      </div>

      <div class="panel chat-panel">
        <div class="panel-title">AI导师（只引导，不给答案）</div>
        <div ref="chatBox" class="chat">
          <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
            <div class="bubble">{{ m.text }}</div>
          </div>
          <div v-if="sending" class="msg tutor"><div class="bubble typing">导师思考中…</div></div>
        </div>
        <div class="composer">
          <textarea
            v-model="draft" rows="2"
            placeholder="描述你观察到的现象、你的猜测、你的验证过程…（Ctrl+Enter发送）"
            @keydown.ctrl.enter="send"
          />
          <button class="primary" :disabled="sending" @click="send">发送</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.error { border-color: var(--red); color: var(--red); margin-bottom: 16px; }
.hint { color: var(--muted); }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px; }
.card { display: flex; flex-direction: column; gap: 8px; }
.card h3 { margin: 0; font-size: 15px; }
.card-head { display: flex; gap: 8px; }
.tag.difficulty { background: #fef3c7; color: #92400e; }
.card-id { font-size: 12px; color: var(--muted); font-family: Consolas, monospace; }
.card button { margin-top: auto; }

.workspace { display: flex; flex-direction: column; gap: 16px; }
.stage-bar { display: flex; align-items: center; gap: 10px; padding: 10px 16px; }
.stage { font-size: 13px; color: var(--muted); }
.stage.active { color: var(--primary); font-weight: 700; }
.stage.done { color: var(--green); }
.spacer { flex: 1; }
.hint-level { font-size: 13px; color: var(--muted); }

.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
.panel-title {
  display: flex; justify-content: space-between; align-items: center;
  font-weight: 600; margin-bottom: 10px;
}
.code {
  width: 100%; height: 420px; resize: vertical;
  background: var(--code-bg); color: var(--code-text);
  font-family: Consolas, 'Courier New', monospace; font-size: 14px;
  line-height: 1.5; border: none; border-radius: 8px; padding: 14px;
  white-space: pre; tab-size: 4;
}
.success { margin-top: 12px; color: var(--green); font-size: 14px; }
.success ol { color: var(--text); }

.chat-panel { display: flex; flex-direction: column; height: 520px; }
.chat { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; padding: 4px; }
.msg { display: flex; }
.msg.student { justify-content: flex-end; }
.bubble {
  max-width: 80%; padding: 8px 12px; border-radius: 12px;
  font-size: 14px; line-height: 1.6; white-space: pre-wrap;
}
.msg.tutor .bubble { background: #f1f5f9; border-bottom-left-radius: 4px; }
.msg.student .bubble { background: var(--primary); color: #fff; border-bottom-right-radius: 4px; }
.msg.system .bubble { background: #fefce8; color: #854d0e; font-size: 13px; max-width: 100%; }
.typing { color: var(--muted); font-style: italic; }
.composer { display: flex; gap: 8px; margin-top: 10px; align-items: flex-end; }
.composer textarea { resize: none; }
</style>
