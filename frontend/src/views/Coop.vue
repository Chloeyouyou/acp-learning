<script setup>
import { ref, reactive, computed, nextTick } from 'vue'
import { api } from '../api'

// ── AI 共脑调试（结对调试）· B0 预置样本 ──
// 与闯关的根本区别：系统不知道答案。AI 只据①真实运行结果②学生说的预期 来引导。
// 完成=学生点「解决了」（唯一门控）。无阶段、无判题、不进画像。

const samples = ref([])              // 可选样本列表 {sample_id, title}
const loadingSamples = ref(true)
const customOpen = ref(false)        // 「贴我自己的代码」表单是否展开
const customCode = ref('')
const customProblem = ref('')
const startingCustom = ref(false)
const session = reactive({ id: null, sampleId: null, title: '', code: '', status: 'active' })
const messages = ref([])             // {role:'student'|'coop'|'system', text}
const draft = ref('')
const running = ref(false)
const sending = ref(false)
const resolving = ref(false)
const busy = computed(() => running.value || sending.value || resolving.value)
const runResult = ref(null)          // {stdout, stderr, timed_out}
const error = ref('')
const chatBox = ref(null)
const done = computed(() => session.status === 'completed')

async function loadSamples() {
  try {
    const d = await api.coopSamples()
    samples.value = d.samples || []
  } catch (e) {
    error.value = '无法连接后端：' + e.message
  } finally {
    loadingSamples.value = false
  }
}
loadSamples()

async function scrollChat() {
  await nextTick()
  if (chatBox.value) chatBox.value.scrollTop = chatBox.value.scrollHeight
}

function enterSession(d) {
  session.id = d.session_id
  session.sampleId = d.sample_id
  session.title = d.title
  session.code = d.code
  session.status = 'active'
  // 首条 = 求助（学生口吻），作为对话起点
  messages.value = [{ role: 'student', text: d.ask }]
  runResult.value = null
  scrollChat()
}

async function start(sampleId) {
  error.value = ''
  runResult.value = null
  try {
    enterSession(await api.coopStart(sampleId))
  } catch (e) {
    error.value = '无法开始：' + e.message
  }
}

async function startCustom() {
  const code = customCode.value.trim()
  if (!code || startingCustom.value) return
  startingCustom.value = true
  error.value = ''
  try {
    enterSession(await api.coopStartCustom(code, customProblem.value.trim()))
    customOpen.value = false
    customCode.value = ''
    customProblem.value = ''
  } catch (e) {
    error.value = '无法开始：' + e.message
  } finally {
    startingCustom.value = false
  }
}

async function runCode() {
  if (busy.value || !session.id) return
  running.value = true
  runResult.value = null
  try {
    runResult.value = await api.coopRun(session.id, session.code)
  } catch (e) {
    runResult.value = { stdout: '', stderr: '运行失败：' + e.message, timed_out: false }
  } finally {
    running.value = false
  }
}

async function send() {
  const text = draft.value.trim()
  if (!text || busy.value) return
  draft.value = ''
  messages.value.push({ role: 'student', text })
  sending.value = true
  scrollChat()
  try {
    const d = await api.coopMessage(session.id, text)
    messages.value.push({ role: 'coop', text: d.reply })
  } catch (e) {
    messages.value.push({ role: 'system', text: '出错了：' + e.message })
  } finally {
    sending.value = false
    scrollChat()
  }
}

async function resolve() {
  if (busy.value || done.value) return
  resolving.value = true
  try {
    await api.coopResolve(session.id)
    session.status = 'completed'
    messages.value.push({ role: 'system', text: '🎉 你点了「解决了」——这一题的结对调试到此结束。换一道，或回去闯关。' })
    scrollChat()
  } catch (e) {
    error.value = '操作失败：' + e.message
  } finally {
    resolving.value = false
  }
}

function quit() {
  session.id = null
  messages.value = []
  runResult.value = null
}

const termText = computed(() => {
  const r = runResult.value
  if (!r) return ''
  if (r.timed_out) return '程序超时、跑不完——很可能卡住了（比如停不下来的循环）。'
  if (r.stderr) return r.stderr
  if (r.stdout) return r.stdout
  return '（程序没有任何输出）'
})
const termBad = computed(() => !!(runResult.value && (runResult.value.stderr || runResult.value.timed_out)))
</script>

<template>
  <div v-if="error" class="panel error">{{ error }}</div>

  <!-- 选样本 -->
  <div v-if="!session.id" class="lobby">
    <div class="lobby-hero">
      <h2 class="lobby-title">AI 共脑调试</h2>
      <p class="lobby-sub">
        和「知返」<b>结对调试</b>——这里没有标准答案，它不会替你写代码，只陪你一起想。
        它只看两样真东西：你<b>真实运行</b>跑出来的结果，和你说的<b>「我本来想要什么」</b>。
      </p>
    </div>
    <div v-if="loadingSamples" class="coop-loading">加载中…</div>
    <div v-else class="sample-grid">
      <button v-for="s in samples" :key="s.sample_id" class="sample-card" @click="start(s.sample_id)">
        <span class="sample-title">{{ s.title }}</span>
        <span class="sample-go">一起看看 →</span>
      </button>
    </div>

    <!-- 贴我自己的代码（B1） -->
    <div v-if="!loadingSamples" class="custom-zone">
      <button v-if="!customOpen" class="custom-trigger" @click="customOpen = true">
        ✍️ 贴我自己的代码 · 让知返陪我一起看
      </button>
      <div v-else class="custom-form">
        <div class="custom-head">
          <b>贴上你自己的代码</b>
          <button class="custom-x" @click="customOpen = false" aria-label="收起">×</button>
        </div>
        <textarea v-model="customCode" class="custom-code" spellcheck="false"
                  placeholder="把你的 Python 代码粘到这里（单个文件就行）…" />
        <input v-model="customProblem" class="custom-problem"
               placeholder="它现在哪儿不对 / 你希望它怎样？（可不填，知返会问你）" />
        <button class="custom-go" :disabled="!customCode.trim() || startingCustom" @click="startCustom">
          {{ startingCustom ? '准备中…' : '开始一起调试 →' }}
        </button>
      </div>
    </div>
  </div>

  <!-- 结对调试工作台 -->
  <div v-else class="coop-wb">
    <div class="coop-top">
      <span class="coop-tag">结对调试 · {{ session.title }}</span>
      <button class="coop-quit" @click="quit">退出</button>
    </div>
    <div class="coop-cols">
      <!-- 左：代码 + 终端 -->
      <div class="coop-left">
        <div class="cc">
          <div class="cc-bar">
            <span class="cc-tab">main.py</span>
            <button class="cc-run" :disabled="busy || done" @click="runCode">
              {{ running ? '运行中…' : '▶ 运行' }}
            </button>
          </div>
          <textarea v-model="session.code" class="cc-ta" spellcheck="false" :disabled="done" />
          <div class="cc-term">
            <div class="cc-term-bar">
              <span class="cc-dots"><i /><i /><i /></span>
              <span class="cc-term-title">终端</span>
              <span class="cc-term-s" :class="{ bad: termBad }">
                {{ runResult ? (runResult.timed_out ? '超时 · 很可能卡住了' : (runResult.stderr ? '运行报错' : '运行成功')) : '还没运行 · 点「运行」看真实结果' }}
              </span>
            </div>
            <pre v-if="runResult" class="cc-term-body" :class="{ err: termBad }">{{ termText }}</pre>
          </div>
        </div>
        <button class="coop-solved" :disabled="busy || done" @click="resolve">
          {{ done ? '✓ 已解决' : '✓ 我搞定了，解决了' }}
        </button>
        <p class="coop-solved-hint">改代码、点运行看结果、和知返聊——你觉得搞定了，就点「解决了」。</p>
      </div>

      <!-- 右：结对对话 -->
      <div class="coop-right">
        <div class="coop-rt-head">
          <span class="coop-avatar">返</span>
          <b>结对调试 · 知返陪你一起想</b>
        </div>
        <div ref="chatBox" class="chat">
          <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
            <div v-if="m.role === 'coop'" class="avatar">知</div>
            <div class="bubble">{{ m.text }}</div>
          </div>
          <div v-if="sending" class="msg coop">
            <div class="avatar">知</div>
            <div class="bubble typing"><span /><span /><span /></div>
          </div>
        </div>
        <div class="composer">
          <textarea v-model="draft" rows="1" :disabled="done"
                    placeholder="说说你看到了什么，或你本来期望它怎样…"
                    @keydown.enter.exact.prevent="send" />
          <button class="send-btn" :disabled="busy || done" @click="send">发送</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.lobby { max-width: 720px; margin: 0 auto; }
.lobby-title { font-family: var(--serif); font-size: 26px; color: var(--text); margin: 0 0 10px; }
.lobby-sub { font-size: 14.5px; color: var(--muted); line-height: 1.8; margin: 0 0 28px; }
.lobby-sub b { color: var(--text); font-weight: 600; }
.coop-loading { color: var(--muted); }
.sample-grid { display: grid; gap: 14px; }
.sample-card {
  display: flex; justify-content: space-between; align-items: center;
  padding: 20px 22px; border: 1px solid var(--border); border-radius: 14px;
  background: var(--panel); cursor: pointer; font-family: inherit; text-align: left;
  transition: border-color 0.15s, transform 0.1s;
}
.sample-card:hover { border-color: var(--primary); transform: translateY(-1px); }
.sample-title { font-size: 16px; color: var(--text); font-weight: 600; }
.sample-go { font-size: 13.5px; color: var(--primary); }

.custom-zone { margin-top: 18px; }
.custom-trigger {
  width: 100%; padding: 16px 22px; border: 1px dashed #cdbba8; border-radius: 14px;
  background: transparent; color: var(--muted); cursor: pointer; font-family: inherit; font-size: 14.5px;
  transition: border-color 0.15s, color 0.15s;
}
.custom-trigger:hover { border-color: var(--primary); color: var(--primary); }
.custom-form { border: 1px solid var(--border); border-radius: 14px; padding: 18px; background: var(--panel); }
.custom-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.custom-head b { font-size: 15px; color: var(--text); }
.custom-x { border: none; background: none; font-size: 22px; color: var(--muted); cursor: pointer; line-height: 1; }
.custom-code {
  width: 100%; min-height: 160px; resize: vertical; box-sizing: border-box;
  border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; background: #fbf7f0;
  font-family: ui-monospace, "Cascadia Code", monospace; font-size: 13.5px; line-height: 1.8;
  color: var(--text); outline: none;
}
.custom-code:focus { border-color: var(--primary); }
.custom-problem {
  width: 100%; box-sizing: border-box; margin-top: 10px; border: 1px solid var(--border);
  border-radius: 10px; padding: 10px 14px; font-family: inherit; font-size: 14px; color: var(--text);
  background: #fff; outline: none;
}
.custom-problem:focus { border-color: var(--primary); }
.custom-go {
  margin-top: 12px; padding: 10px 20px; border: none; border-radius: 10px; cursor: pointer;
  background: var(--primary); color: #fff; font-family: var(--serif); font-size: 14.5px; font-weight: 600;
}
.custom-go:disabled { opacity: 0.5; cursor: not-allowed; }

.coop-wb { max-width: 1120px; margin: 0 auto; }
.coop-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.coop-tag { font-size: 14px; color: var(--muted); }
.coop-quit {
  font-size: 13px; color: var(--muted); background: var(--accent-soft); border: 1px solid transparent;
  padding: 5px 14px; border-radius: 999px; cursor: pointer; font-family: inherit;
}
.coop-quit:hover { color: var(--text); border-color: #dac9b8; }
.coop-cols { display: flex; gap: 20px; align-items: flex-start; }
.coop-left { flex: 1; min-width: 0; }
.coop-right { flex: 1; min-width: 0; display: flex; flex-direction: column; height: 560px; }

.cc { border: 1px solid var(--border); border-radius: 14px; overflow: hidden; background: #fbf7f0; }
.cc-bar { display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; border-bottom: 1px solid var(--border); }
.cc-tab { font-size: 12.5px; color: var(--muted); font-family: ui-monospace, monospace; }
.cc-run {
  font-size: 13px; color: #fff; background: var(--primary); border: none;
  padding: 5px 14px; border-radius: 8px; cursor: pointer; font-family: inherit;
}
.cc-run:disabled { opacity: 0.5; cursor: not-allowed; }
.cc-ta {
  width: 100%; min-height: 200px; border: none; outline: none; resize: vertical;
  padding: 14px 16px; font-family: ui-monospace, "Cascadia Code", monospace; font-size: 13.5px;
  line-height: 1.9; color: var(--text); background: transparent; box-sizing: border-box;
}
.cc-ta:disabled { color: var(--muted); }
.cc-term { border-top: 1px solid var(--border); background: #221f1c; }
.cc-term-bar { display: flex; align-items: center; gap: 10px; padding: 7px 12px; }
.cc-dots { display: inline-flex; gap: 4px; }
.cc-dots i { width: 9px; height: 9px; border-radius: 50%; background: #4a443e; }
.cc-term-title { font-size: 12px; color: #b8b0a6; }
.cc-term-s { font-size: 12px; color: #9fd29f; margin-left: auto; }
.cc-term-s.bad { color: #e6a36a; }
.cc-term-body {
  margin: 0; padding: 10px 14px 14px; font-family: ui-monospace, monospace; font-size: 12.5px;
  line-height: 1.7; color: #d8d2c8; white-space: pre-wrap; word-break: break-word; max-height: 180px; overflow: auto;
}
.cc-term-body.err { color: #f0b48a; }

.coop-solved {
  width: 100%; margin-top: 14px; padding: 12px; border: none; border-radius: 12px; cursor: pointer;
  background: var(--primary); color: #fff; font-family: var(--serif); font-size: 15px; font-weight: 600;
}
.coop-solved:disabled { opacity: 0.55; cursor: not-allowed; }
.coop-solved-hint { font-size: 12.5px; color: var(--muted); text-align: center; margin: 8px 0 0; line-height: 1.6; }

.coop-rt-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; font-size: 14px; color: var(--text); }
.coop-avatar {
  width: 30px; height: 30px; border-radius: 50%; background: var(--primary); color: #fff;
  display: grid; place-items: center; font-family: var(--serif); font-size: 15px;
}
.chat { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; padding: 4px; }
.msg { display: flex; gap: 8px; max-width: 92%; }
.msg.student { align-self: flex-end; }
.msg .avatar {
  width: 26px; height: 26px; border-radius: 50%; background: var(--accent-soft); color: var(--primary);
  display: grid; place-items: center; font-size: 13px; flex-shrink: 0;
}
.bubble {
  padding: 9px 13px; border-radius: 12px; font-size: 14px; line-height: 1.7; white-space: pre-wrap; word-break: break-word;
}
.msg.coop .bubble, .msg.system .bubble { background: var(--panel); border: 1px solid var(--border); color: var(--text); }
.msg.student .bubble { background: var(--primary); color: #fff; }
.msg.system .bubble { color: var(--muted); font-size: 13px; }
.bubble.typing { display: inline-flex; gap: 4px; }
.bubble.typing span { width: 6px; height: 6px; border-radius: 50%; background: var(--muted); animation: blink 1.2s infinite; }
.bubble.typing span:nth-child(2) { animation-delay: 0.2s; }
.bubble.typing span:nth-child(3) { animation-delay: 0.4s; }
@keyframes blink { 0%, 80%, 100% { opacity: 0.3; } 40% { opacity: 1; } }

.composer { display: flex; gap: 8px; margin-top: 12px; }
.composer textarea {
  flex: 1; resize: none; border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px;
  font-family: inherit; font-size: 14px; outline: none; background: #fff; color: var(--text);
}
.composer textarea:focus { border-color: var(--primary); }
.send-btn {
  border: none; border-radius: 10px; padding: 0 18px; background: var(--primary); color: #fff;
  cursor: pointer; font-family: inherit; font-size: 14px;
}
.send-btn:disabled { opacity: 0.5; cursor: not-allowed; }

@media (max-width: 760px) {
  .coop-cols { flex-direction: column; }
  .coop-right { width: 100%; height: 460px; }
}
</style>
