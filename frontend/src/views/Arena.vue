<script setup>
import { onMounted, reactive, ref, computed, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import GlossaryText from '../components/GlossaryText.vue'
import { GLOSSARY, bricksInCode } from '../glossary'

const route = useRoute()
const router = useRouter()

const STAGES = ['①发现', '②定位', '③归因', '④修复', '⑤验证', '⑥内化']

// Bug 分类：中文名 + 一句话说明（决定大厅分组的顺序与文案）
const CATEGORY_META = {
  boundary: { label: '边界类', desc: '数组越界、差一错误——和「范围」打交道时最常见的坑。' },
  loop: { label: '循环类', desc: '循环次数、终止条件、累加逻辑里的细节失误。' },
  null: { label: '空值类', desc: '空对象、缺字段、None——没防住「什么都没有」的情况。' },
  arithmetic: { label: '算术类', desc: '除零、溢出等数值运算中的边界问题。' },
}
const CATEGORY_ORDER = ['boundary', 'loop', 'null', 'arithmetic']
function catMeta(c) {
  return CATEGORY_META[c] || { label: c, desc: '' }
}
function stageIndex(s) { return STAGES.indexOf(s) }

// 按类型分组（固定顺序，组内按难度升序），降低「一次 15 张卡」的密度
const grouped = computed(() => {
  const byCat = {}
  for (const p of patterns.value) (byCat[p.category] ||= []).push(p)
  const order = [...CATEGORY_ORDER, ...Object.keys(byCat).filter((c) => !CATEGORY_ORDER.includes(c))]
  return order
    .filter((c) => byCat[c]?.length)
    .map((c) => ({
      category: c,
      ...catMeta(c),
      items: byCat[c].sort((a, b) => (a.difficulty || '').localeCompare(b.difficulty || '')),
    }))
})


const patterns = ref([])
const lobbyMode = ref('smart')   // 'smart' 智能推荐 | 'browse' 自己挑选
const recs = ref([])             // 个性化推荐（后端按能力画像生成）
const recsLoading = ref(false)
const openCats = reactive({})    // 自己挑选模式：哪些分组已展开（默认只开第一组）
const session = reactive({
  id: null, patternId: null, code: '', task: '', stage: '①发现', hintLevel: 'L0',
  fixed: false,      // 代码已通过测试（进入⑤验证），但本关尚未结束
  done: false,       // ⑥内化判定通过，本关结束
  internalizeQuestions: [],
  variant: null,     // 内化通过后推荐的变式题（迁移检验）
})
const masteredKps = ref(new Set())   // 学生已内化的知识点（练前小灶用来标「已掌握」）
const showPrimer = ref(false)        // 练前小灶默认收起（需要的人再点开），避免页面被撑长
const showSyntax = ref(false)        // 「代码怎么读」符号扫盲是否展开（默认收起，需要的人点开）
const walkthrough = ref('')          // 逐行讲解文本（点按钮自动生成）
const walkLoading = ref(false)
const running = ref(false)           // 运行按钮状态
const runResult = ref(null)          // {stdout, stderr, timed_out}
// 代码一改，旧的运行结果就作废——否则会出现"删了代码却还显示上次成功输出"的错觉
watch(() => session.code, () => { runResult.value = null })

async function runCurrentCode() {
  if (running.value || !session.id) return
  running.value = true
  runResult.value = null
  try {
    runResult.value = await api.runCode(session.id, session.code)
    // B0.5：每关首次运行、且还在①发现阶段，弹观察卡（软桥，不锁聊天）
    if (!observationDone.value && session.stage === '①发现') {
      // 按真实运行结果智能预勾，降低零基础负担（学生仍可改）
      Object.keys(obsChecks).forEach((k) => { obsChecks[k] = false })
      if (runResult.value.timed_out) obsChecks['程序卡住了/跑不完'] = true
      else if (runResult.value.stderr) obsChecks['程序报错了'] = true
      observationPending.value = true
    }
  } catch (e) {
    runResult.value = { stdout: '', stderr: '运行失败：' + e.message, timed_out: false }
  } finally {
    running.value = false
  }
}
const walkDeep = ref(false)          // 是否已是「更详细」档
// 已掌握的语法符号（用户点「懂了」后记住，以后不再展示，列表越用越短）
const learnedBricks = ref(new Set(JSON.parse(localStorage.getItem('learned_bricks') || '[]')))

// 把「代码 —— 解释」文本解析成一行行，渲染成和代码一一对应的样子
// 容错：LLM 偶尔用单个 — 或 –，统一按 em-dash 连写切分（代码几乎不含破折号，安全）
const walkRows = computed(() => {
  if (!walkthrough.value) return []
  return walkthrough.value.split('\n').map((l) => l.trim()).filter(Boolean).map((line) => {
    const m = line.match(/[—–]+/)
    if (!m) return { code: '', explain: line }
    return { code: line.slice(0, m.index).trim(), explain: line.slice(m.index + m[0].length).trim() }
  })
})

// 过滤掉用户已标「懂了」的符号
const visibleBricks = computed(() => syntaxBricks.value.filter((b) => !learnedBricks.value.has(b.name)))
const hiddenBricks = computed(() => syntaxBricks.value.filter((b) => learnedBricks.value.has(b.name)))
const showHiddenBricks = ref(false)   // 「已隐藏的符号」管理区是否展开

function persistBricks() {
  localStorage.setItem('learned_bricks', JSON.stringify([...learnedBricks.value]))
}
function markBrickLearned(name) {
  learnedBricks.value.add(name)
  persistBricks()
}
function restoreBrick(name) {        // 单个恢复
  learnedBricks.value.delete(name)
  persistBricks()
}
function resetLearnedBricks() {      // 全部恢复
  learnedBricks.value = new Set()
  localStorage.removeItem('learned_bricks')
}

async function loadWalkthrough(deep = false) {
  if (walkLoading.value || !session.patternId) return
  if (!deep && walkthrough.value) return        // 标准档已加载过就不重复
  walkLoading.value = true
  try {
    const d = await api.getWalkthrough(session.patternId, deep)
    walkthrough.value = d.walkthrough || ''
    walkDeep.value = deep
  } catch (e) {
    walkthrough.value = '讲解生成失败，可以把看不懂的那一行直接发给导师问。'
  } finally {
    walkLoading.value = false
  }
}

// 「代码怎么读」：这道题代码里实际出现的语法符号，给完全没见过代码的人扫盲
const syntaxBricks = computed(() => bricksInCode(session.code))

// 练前小灶：这道题涉及的概念，用大白话先补一补；已掌握的标出来，只重点补没学过的
const primerConcepts = computed(() => {
  const p = patterns.value.find((x) => x.id === session.patternId)
  if (!p || !p.knowledge_points) return []
  return p.knowledge_points.map((kp) => ({
    kp,
    desc: GLOSSARY[kp] || GLOSSARY[kp.toLowerCase()] || '',
    mastered: masteredKps.value.has(kp),
  }))
})
function toggleCat(c) { openCats[c] = !openCats[c] }
const messages = ref([]) // {role: 'student'|'tutor'|'system', text}
const draft = ref('')
const sending = ref(false)
const submitting = ref(false)
const error = ref('')
const chatBox = ref(null)

onMounted(async () => {
  try {
    patterns.value = await api.listPatterns()
    if (grouped.value[0]) openCats[grouped.value[0].category] = true  // 默认只展开第一组
  } catch (e) {
    error.value = '无法连接后端：' + e.message
  }
  loadRecs()
  loadMastered()
  // 从能力画像「做变式巩固」跳来：自动开始指定关卡（优先于续做）
  if (route.query.start) {
    const pid = String(route.query.start)
    router.replace({ query: {} })  // 清掉 query，避免刷新重复触发
    start(pid)
    return
  }
  // 断点续做：上次有未完成的关卡（非主动退出）→ 自动恢复对话与阶段
  const saved = localStorage.getItem('active_session')
  if (saved) {
    try {
      const d = await api.getSession(saved)
      if (d.status === 'active') {
        session.id = d.session_id
        session.patternId = d.pattern_id
        session.code = d.code
        session.stage = d.stage
        session.hintLevel = d.hint_level
        session.fixed = d.fixed
        session.done = d.done
        session.internalizeQuestions = d.internalize_questions || []
        session.variant = null
        observationDone.value = true   // 续做：已在进行中，不再弹观察卡
        messages.value = d.messages
        messages.value.push({ role: 'system', text: '↩️ 已恢复你上次未完成的关卡，接着来吧。' })
      } else {
        localStorage.removeItem('active_session')
      }
    } catch (e) {
      localStorage.removeItem('active_session')
    }
  }
})

async function loadRecs() {
  recsLoading.value = true
  try {
    recs.value = await api.getRecommendations()
  } catch (e) {
    recs.value = []
  } finally {
    recsLoading.value = false
  }
}

async function loadMastered() {
  try {
    const prof = await api.getProfile()
    const set = new Set()
    for (const s of prof.knowledge_states || []) {
      if (s.state === '已内化') (s.knowledge_points || []).forEach((k) => set.add(k))
    }
    masteredKps.value = set
  } catch (e) { /* 拿不到就当都没掌握，照常显示 */ }
}

async function start(patternId) {
  error.value = ''
  try {
    const data = await api.createSession(patternId)
    session.id = data.session_id
    session.patternId = patternId
    showPrimer.value = false  // 新关卡练前小灶默认收起，需要的人再点开
    walkthrough.value = ''    // 清掉上一题的逐行讲解
    walkDeep.value = false
    runResult.value = null
    resetObservation()
    localStorage.setItem('active_session', data.session_id)  // 记下当前关卡，供刷新后续做
    session.code = data.code
    session.task = data.task
    session.stage = '①发现'
    session.hintLevel = 'L0'
    session.fixed = false
    session.done = false
    session.internalizeQuestions = []
    session.variant = null
    messages.value = [{ role: 'system', text: data.task }]
  } catch (e) {
    error.value = e.message
  }
}

async function scrollChat() {
  await nextTick()
  if (chatBox.value) chatBox.value.scrollTop = chatBox.value.scrollHeight
}

// 发送任意一条学生消息给导师（供输入框 send 与观察卡共用）
async function sendText(text) {
  if (!text || sending.value) return
  messages.value.push({ role: 'student', text })
  sending.value = true
  scrollChat()
  try {
    const d = await api.sendMessage(session.id, text)
    messages.value.push({ role: 'tutor', text: d.reply })
    session.stage = d.stage
    session.hintLevel = d.hint_level
    if (d.session_status === 'completed') {
      session.done = true
      messages.value.push({ role: 'system', text: '🎉 内化判定通过！该知识点已升级为「已内化」，本关完成。' })
      session.variant = d.variant || null   // 推荐的变式题（迁移检验）
    }
  } catch (e) {
    messages.value.push({ role: 'system', text: '出错了：' + e.message })
  } finally {
    sending.value = false
    scrollChat()
  }
}

async function send() {
  const text = draft.value.trim()
  if (!text || sending.value) return
  draft.value = ''
  await sendText(text)
}

// ── B0.5 观察卡：运行→观察→猜测→导师，软桥、可跳过、不硬锁 ──
// 学生消息统一前缀 OBSERVATION_MARK，便于未来 B1 Timeline 抽取
const OBSERVATION_MARK = '【观察记录】'
const observationPending = ref(false)   // 是否显示观察卡
const observationDone = ref(false)      // 本关是否已观察过（每关首次运行触发一次）
const obsChecks = reactive({ 程序报错了: false, '程序卡住了/跑不完': false, 输出和预期不同: false, 输出正确: false, 我还没看懂: false })
const obsGuess = ref('')

function resetObservation() {
  observationPending.value = false
  observationDone.value = false
  obsGuess.value = ''
  Object.keys(obsChecks).forEach((k) => { obsChecks[k] = false })
}

async function submitObservation() {
  const picked = Object.keys(obsChecks).filter((k) => obsChecks[k])
  const seen = picked.length ? picked.join('、') : '（没勾选，先凭感觉看看）'
  const guess = obsGuess.value.trim() || '（暂时说不上来）'
  const text = `${OBSERVATION_MARK}\n我观察到：${seen}\n我的猜测：${guess}`
  observationPending.value = false
  observationDone.value = true
  await sendText(text)
}

async function skipObservation() {
  observationPending.value = false
  observationDone.value = true
  await sendText(`${OBSERVATION_MARK}\n我运行了代码，但暂时描述不出观察，请帮我一起分析。`)
}

async function submit() {
  if (submitting.value) return
  submitting.value = true
  // 先显示"你提交了一次"这个动作——否则提交失败时只剩导师回复，连提两次会像导师自言自语
  messages.value.push({ role: 'student', text: '📤 我提交了一版修复' })
  scrollChat()
  try {
    const d = await api.submitFix(session.id, session.code)
    if (d.stage) session.stage = d.stage
    if (d.passed) {
      session.fixed = true
      session.internalizeQuestions = d.internalize_questions || []
      messages.value.push({ role: 'system', text: d.message })
      // 导师主动开场，引导进入⑤验证——学生不用自己猜该说什么
      if (d.tutor_opening) messages.value.push({ role: 'tutor', text: d.tutor_opening })
    } else {
      // 失败反馈来自导师（针对提交代码的具体引导），按导师气泡展示
      messages.value.push({ role: 'tutor', text: d.message })
    }
  } catch (e) {
    messages.value.push({ role: 'system', text: '提交失败：' + e.message })
  } finally {
    submitting.value = false
    scrollChat()
  }
}

function quit() {
  localStorage.removeItem('active_session')  // 主动退出 = 放弃续做
  session.id = null
  messages.value = []
  loadRecs()  // 闯关后能力可能变化，回大厅刷新个性化推荐
}
</script>

<template>
  <div v-if="error" class="panel error">{{ error }}</div>

  <!-- 选题 -->
  <div v-if="!session.id" class="lobby">
    <div class="lobby-hero">
      <h2>Bug 闯关训练场</h2>
      <p class="hint">
        每一关的代码里都藏着一个真实 Bug。你的任务是<b>发现它</b>、和 AI 导师一起<b>定位它</b>、
        亲手<b>修好它</b>，再讲清楚它为什么会发生——走完六步，知识点才真正属于你。
      </p>
    </div>

    <!-- 模式切换 -->
    <div class="mode-tabs">
      <button :class="['mode-tab', { on: lobbyMode === 'smart' }]" @click="lobbyMode = 'smart'">✦ 智能推荐</button>
      <button :class="['mode-tab', { on: lobbyMode === 'browse' }]" @click="lobbyMode = 'browse'">浏览全部题目</button>
    </div>

    <!-- 智能推荐：只给少数几题 + 推荐理由 -->
    <div v-if="lobbyMode === 'smart'" class="smart">
      <p v-if="recsLoading" class="hint">正在根据你的能力画像生成推荐…</p>
      <p v-else-if="!recs.length" class="hint">暂时没有可推荐的题目——你可能已经把现有题目都内化了，去「浏览全部题目」复习吧。</p>
      <div v-else class="rec-list">
        <button v-for="(r, i) in recs" :key="r.id" :class="['rec-card', { featured: i === 0 }]" @click="start(r.id)">
          <div class="rec-main">
            <span class="rec-reason">{{ i === 0 ? '🎯 ' : '' }}{{ r.reason }}</span>
            <span class="rec-name">{{ r.name }}</span>
            <div class="rec-meta">
              <span class="diff-badge">{{ r.difficulty }}</span>
              <span v-for="kp in r.knowledge_points" :key="kp" class="kp-tag">{{ kp }}</span>
              <span v-if="r.state !== '未接触'" class="state-chip">{{ r.state }}</span>
            </div>
          </div>
          <span class="rec-cta">{{ i === 0 ? '开始挑战 →' : '挑战 →' }}</span>
        </button>
      </div>
      <p class="smart-foot">想自己挑？切到「浏览全部题目」，{{ patterns.length }} 道题按类型分好了组。</p>
    </div>

    <!-- 自己挑选：按类型分组，默认只展开第一组 -->
    <template v-else>
      <section v-for="g in grouped" :key="g.category" class="cat-group">
        <button class="cat-group-head" @click="toggleCat(g.category)">
          <span class="cat-caret" :class="{ open: openCats[g.category] }">▸</span>
          <span class="cat-title">{{ g.label }}<span class="cat-count">{{ g.items.length }} 题</span></span>
          <span class="cat-desc">{{ g.desc }}</span>
        </button>
        <div v-show="openCats[g.category]" class="cards">
          <button v-for="p in g.items" :key="p.id" class="card" @click="start(p.id)">
            <div class="card-head">
              <h3>{{ p.name }}</h3>
              <span class="diff-badge">{{ p.difficulty }}</span>
            </div>
            <div v-if="p.knowledge_points?.length" class="kp-tags">
              <span v-for="kp in p.knowledge_points" :key="kp" class="kp-tag">{{ kp }}</span>
            </div>
            <span class="card-cta">开始挑战 →</span>
          </button>
        </div>
      </section>
    </template>
  </div>

  <!-- 做题 -->
  <div v-else class="workspace">
    <div class="stage-bar panel">
      <ol class="stepper">
        <li
          v-for="s in STAGES" :key="s"
          :class="['step', { active: s === session.stage, done: stageIndex(s) < stageIndex(session.stage) }]"
        >
          <span class="step-no">{{ stageIndex(s) < stageIndex(session.stage) ? '✓' : s.charAt(0) }}</span>
          <span class="step-label">{{ s.slice(1) }}</span>
        </li>
      </ol>
      <div class="stage-meta">
        <span class="hint-level">提示级别 <b>{{ session.hintLevel }}</b></span>
        <button @click="quit">退出关卡</button>
      </div>
    </div>

    <!-- 练前小灶：这道题用到的概念，看不懂代码先补一补（个性化：已掌握的标出来） -->
    <div v-if="primerConcepts.length" class="primer panel">
      <button class="primer-head" @click="showPrimer = !showPrimer">
        <span class="primer-caret" :class="{ open: showPrimer }">▸</span>
        💡 <b>看不懂代码？点开练前小灶</b> · 认符号 / 逐行讲解 / 概念
      </button>
      <div v-show="showPrimer" class="primer-body">
        <!-- 代码符号扫盲：完全没见过代码的人先认认这些符号；标「懂了」的可单个/全部恢复 -->
        <div v-if="visibleBricks.length || hiddenBricks.length" class="syntax-box">
          <button class="syntax-head" @click="showSyntax = !showSyntax">
            <span class="primer-caret" :class="{ open: showSyntax }">▸</span>
            🔤 完全没接触过代码？先认认这道题里的符号（{{ visibleBricks.length }} 个）
          </button>
          <div v-show="showSyntax" class="syntax-list">
            <div v-for="b in visibleBricks" :key="b.name" class="syntax-item">
              <div class="syntax-row">
                <span class="syntax-name">{{ b.name }}</span>
                <button class="brick-known" title="标记懂了，以后不再显示" @click="markBrickLearned(b.name)">✓ 懂了</button>
              </div>
              <span class="syntax-desc">{{ b.desc }}</span>
            </div>
            <div v-if="visibleBricks.length === 0" class="brick-allknown">这道题的符号你都标记懂了 👍</div>
            <!-- 已隐藏符号管理：可展开逐个恢复，或一键全部恢复 -->
            <div v-if="hiddenBricks.length" class="brick-hidden">
              <button class="brick-toggle" @click="showHiddenBricks = !showHiddenBricks">
                已隐藏 {{ hiddenBricks.length }} 个你标记懂了的符号 {{ showHiddenBricks ? '▾' : '▸' }}
              </button>
              <div v-show="showHiddenBricks" class="hidden-list">
                <div v-for="b in hiddenBricks" :key="b.name" class="hidden-item">
                  <span class="syntax-name">{{ b.name }}</span>
                  <button class="brick-restore" @click="restoreBrick(b.name)">↩ 恢复</button>
                </div>
                <button class="brick-reset" @click="resetLearnedBricks">全部恢复</button>
              </div>
            </div>
          </div>
        </div>
        <!-- 逐行讲解：AI 把代码翻译成大白话，和代码一行一行对应（不剧透 bug） -->
        <div class="walk-box">
          <button v-if="!walkthrough && !walkLoading" class="walk-btn" @click="loadWalkthrough(false)">
            📖 还是看不懂这段代码？让导师逐行讲给我听
          </button>
          <div v-else-if="walkLoading" class="walk-loading">导师正在逐行讲解…</div>
          <template v-else>
            <div class="walk-rows">
              <div v-for="(r, i) in walkRows" :key="i" class="walk-row">
                <code v-if="r.code" class="walk-code">{{ r.code }}</code>
                <div class="walk-exp">{{ r.explain }}</div>
              </div>
            </div>
            <button v-if="!walkDeep" class="walk-deep" @click="loadWalkthrough(true)">
              还不够懂？再讲细一点 →
            </button>
            <div v-else class="walk-deep-done">已是最详细的讲法 · 还不懂就把那一行发给导师问</div>
          </template>
        </div>
        <div class="primer-sub">这道题涉及的概念：</div>
        <div v-for="c in primerConcepts" :key="c.kp" class="primer-item">
          <div class="primer-term">
            {{ c.kp }}
            <span v-if="c.mastered" class="primer-tag done">✓ 你已掌握</span>
            <span v-else class="primer-tag new">新概念</span>
          </div>
          <div class="primer-desc">{{ c.desc || '（这个概念暂时没有简介，遇到不懂的随时问导师）' }}</div>
        </div>
        <p class="primer-foot">做题时，对话里带虚线的词也能悬停看解释。准备好了就直接和导师开始吧 👇</p>
      </div>
    </div>

    <div class="cols">
      <div class="panel code-panel">
        <div class="panel-title">
          <span class="title-text">代码 · 直接在这里修改</span>
          <span class="code-actions">
            <button :disabled="running" @click="runCurrentCode">
              {{ running ? '运行中…' : '▶ 运行' }}
            </button>
            <button class="primary" :disabled="submitting || session.fixed" @click="submit">
              {{ submitting ? '判定中…' : '提交修复' }}
            </button>
          </span>
        </div>
        <textarea v-model="session.code" class="code" spellcheck="false" :disabled="session.fixed" />
        <!-- 运行结果：学生自己跑、自己看真实输出/报错（路线A，真运行非AI猜） -->
        <div v-if="runResult" class="run-result">
          <div class="run-result-head" :class="{ ok: !runResult.stderr && !runResult.timed_out, bad: runResult.stderr || runResult.timed_out }">
            {{ runResult.timed_out ? '⏱ 运行超时（很可能死循环）' : (runResult.stderr ? '✗ 程序报错了' : '✓ 程序运行成功') }}
            <span class="run-real">真实运行结果</span>
          </div>
          <div v-if="runResult.stdout" class="run-block">
            <div class="run-label">标准输出 stdout</div>
            <pre class="run-out">{{ runResult.stdout }}</pre>
          </div>
          <div v-if="runResult.stderr" class="run-block">
            <div class="run-label">报错 stderr</div>
            <pre class="run-err">{{ runResult.stderr }}</pre>
          </div>
          <div v-if="!runResult.stdout && !runResult.stderr && !runResult.timed_out" class="run-empty">（程序没有任何输出）</div>
        </div>

        <!-- B0.5 观察卡：运行后先观察再问导师（软桥，可跳过，不锁聊天） -->
        <div v-if="observationPending" class="obs-card">
          <div class="obs-title">🔍 先别急着问导师——你观察到了什么？</div>
          <div class="obs-hint">对照上面的运行结果，勾一勾、写一写，再发给导师。说不出来也没关系。</div>
          <label v-for="(_, k) in obsChecks" :key="k" class="obs-check">
            <input type="checkbox" v-model="obsChecks[k]" /> {{ k }}
          </label>
          <textarea v-model="obsGuess" class="obs-guess" rows="2"
                    placeholder="我的猜测：问题可能出在……（写不出来可以留空）" />
          <div class="obs-actions">
            <button class="primary" :disabled="sending" @click="submitObservation">把观察告诉导师 →</button>
            <button class="obs-skip" :disabled="sending" @click="skipObservation">我看不懂，直接请导师帮助</button>
          </div>
        </div>

        <div v-if="session.done" class="banner banner-done">
          🎉 <b>本关完成！</b>该知识点已升级为「已内化」（成因 / 定位 / 迁移复述通过）。去能力画像看看，或挑战下一题。
          <div v-if="session.variant" class="variant-offer">
            <span class="variant-label">想检验是否真的学会？试试这道<b>同类变式题</b>——独立解出才算迁移到位：</span>
            <button class="primary variant-btn" @click="start(session.variant.id)">
              挑战变式：{{ session.variant.name }} →
            </button>
          </div>
        </div>
        <div v-else-if="session.fixed" class="banner banner-fixed">
          <div class="bf-title">代码修对了 · 进度到 ⑤验证（还没结束）</div>
          <div class="bf-body">
            这只是<b>「已解决」</b>——会改 ≠ 真懂。<b>「已解决」≠「已掌握」</b>。
            接着和导师走完 ⑤验证（边界测试）与 ⑥内化（讲清成因/定位/迁移），知识点才升级为「已内化」，这一关才算真正学会。
          </div>
        </div>
      </div>

      <div class="panel chat-panel">
        <div class="panel-title">
          <span class="title-text"><span class="tutor-avatar">AI</span>AI 导师</span>
          <span class="title-sub">只引导，不给答案</span>
        </div>
        <div ref="chatBox" class="chat">
          <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
            <div v-if="m.role === 'tutor'" class="avatar tutor-avatar">AI</div>
            <div class="bubble">
              <GlossaryText v-if="m.role !== 'student'" :text="m.text" />
              <template v-else>{{ m.text }}</template>
            </div>
          </div>
          <div v-if="sending" class="msg tutor">
            <div class="avatar tutor-avatar">AI</div>
            <div class="bubble typing"><span /><span /><span /></div>
          </div>
        </div>
        <div class="composer">
          <textarea
            v-model="draft" rows="2"
            placeholder="描述你观察到的现象、你的猜测、你的验证过程…（Ctrl+Enter 发送）"
            @keydown.ctrl.enter="send"
          />
          <button class="primary send-btn" :disabled="sending" @click="send">发送</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.error { border-color: var(--red); color: var(--red); margin-bottom: 16px; }

/* ========== 方向 D：Anthropic 暖调克制风（象牙底 + 陶土点缀 + 衬线标题 + 大留白） ========== */
/* ---------- 选题大厅 ---------- */
.lobby { padding-top: 4px; }
.lobby-hero {
  margin-bottom: 28px;
  max-width: 720px;
}
.lobby-hero h2 { margin: 0 0 14px; font-size: 30px; font-weight: 600; line-height: 1.25; }
.hint { color: var(--muted); margin: 0; line-height: 1.8; font-size: 15px; }
.hint b { color: var(--text); font-weight: 600; }

/* 模式切换 */
.mode-tabs { display: inline-flex; gap: 4px; padding: 4px; margin-bottom: 26px;
  background: #ece6da; border-radius: 11px; }
.mode-tab {
  border: none; background: transparent; color: var(--muted); font-size: 14px;
  padding: 7px 16px; border-radius: 8px; font-family: var(--serif);
}
.mode-tab:hover:not(.on) { color: var(--text); }
.mode-tab.on { background: var(--panel); color: var(--primary); box-shadow: 0 1px 3px rgba(43,41,36,0.08); }

/* 智能推荐 */
.rec-list { display: flex; flex-direction: column; gap: 14px; }
.rec-card {
  display: flex; align-items: center; justify-content: space-between; gap: 16px; width: 100%;
  text-align: left; padding: 18px 22px; cursor: pointer;
  background: var(--panel); border: 1px solid var(--border); border-radius: 14px;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.rec-card:hover {
  transform: translateY(-2px); color: inherit; border-color: #dac9b8;
  box-shadow: 0 14px 30px -16px rgba(193, 95, 60, 0.4);
}
/* 高亮卡：用 featured 而非 primary，避免和全局 button.primary（实心橙底）冲突 */
.rec-card.featured { background: var(--accent-soft); border-color: #e0cdbb; }
/* 高亮卡背景已是浅陶土，标签/状态需换底色才不会和卡片融在一起 */
.rec-card.featured .kp-tag { background: var(--panel); }
.rec-card.featured .state-chip { background: var(--panel); border-color: #d8c6b4; }
.rec-main { display: flex; flex-direction: column; gap: 7px; }
.rec-reason { font-size: 13px; font-weight: 600; color: var(--primary); }
.rec-name { font-family: var(--serif); font-size: 17px; font-weight: 600; color: var(--text); }
.rec-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; }
.rec-cta {
  font-family: var(--serif); font-size: 14.5px; font-weight: 600; color: var(--primary); flex-shrink: 0;
  transition: transform 0.18s;
}
.rec-card:hover .rec-cta { transform: translateX(4px); }
.state-chip {
  font-size: 11.5px; color: var(--muted); border: 1px solid var(--border);
  padding: 1px 8px; border-radius: 999px;
}
.smart-foot { margin: 20px 0 0; font-size: 13px; color: var(--muted); }

/* 分类分组（可折叠） */
.cat-group { margin-bottom: 14px; border-bottom: 1px solid var(--border); padding-bottom: 14px; }
.cat-group:last-child { border-bottom: none; }
.cat-group-head {
  display: flex; align-items: baseline; gap: 10px; width: 100%; text-align: left;
  background: none; border: none; padding: 8px 2px; margin-bottom: 6px; cursor: pointer; flex-wrap: wrap;
}
.cat-caret { color: var(--muted); font-size: 12px; transition: transform 0.18s; align-self: center; }
.cat-caret.open { transform: rotate(90deg); }
.cat-title { font-family: var(--serif); font-size: 18px; font-weight: 600; color: var(--text); }
.cat-count { font-size: 12.5px; font-weight: 400; color: var(--muted); margin-left: 8px; }
.cat-desc { font-size: 13px; color: var(--muted); line-height: 1.6; flex: 1; min-width: 200px; }
.cards { margin-top: 14px; }

.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(272px, 1fr)); gap: 16px; }
.card {
  display: flex; flex-direction: column; align-items: stretch; gap: 12px; text-align: left;
  background: var(--panel); border: 1px solid var(--border); border-radius: 14px;
  padding: 20px; cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.card:hover {
  transform: translateY(-3px); border-color: #dac9b8; color: inherit;
  box-shadow: 0 14px 30px -16px rgba(193, 95, 60, 0.4);
}
.card-head { display: flex; gap: 10px; align-items: flex-start; }
.card-head h3 { margin: 0; font-size: 15.5px; line-height: 1.45; font-weight: 600; flex: 1; }
.diff-badge {
  margin-left: auto; flex-shrink: 0; font-size: 12px; color: var(--muted);
  border: 1px solid var(--border); padding: 2px 9px; border-radius: 6px;
}
.kp-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.kp-tag {
  font-size: 12px; padding: 2px 9px; border-radius: 6px;
  background: var(--accent-soft); color: var(--primary-dark);
}
.card-cta {
  margin-top: 4px; font-size: 13.5px; font-weight: 500; color: var(--primary);
  font-family: var(--serif); transition: transform 0.18s;
}
.card:hover .card-cta { transform: translateX(4px); }

/* ---------- 阶段步进条 ---------- */
.workspace { display: flex; flex-direction: column; gap: 20px; }
.stage-bar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 16px; padding: 14px 22px; flex-wrap: wrap;
}
.stepper { display: flex; align-items: center; gap: 0; margin: 0; padding: 0; list-style: none; flex-wrap: wrap; }
.step { display: flex; align-items: center; gap: 8px; color: var(--muted); position: relative; padding-right: 6px; }
.step:not(:last-child)::after {
  content: ''; width: 26px; height: 1px; background: var(--border); margin: 0 10px 0 8px;
}
.step-no {
  display: inline-flex; align-items: center; justify-content: center;
  width: 26px; height: 26px; border-radius: 50%; font-size: 12px; font-weight: 600;
  background: #ece6da; color: var(--muted); transition: all 0.2s;
}
.step-label { font-size: 13.5px; }
.step.active .step-no { background: var(--primary); color: #fff; box-shadow: 0 0 0 4px var(--accent-soft); }
.step.active .step-label { color: var(--text); font-weight: 600; }
.step.done .step-no { background: #cbb9a6; color: #fff; }
.step.done .step-label { color: var(--muted); }
.stage-meta { display: flex; align-items: center; gap: 16px; }
.hint-level { font-size: 13px; color: var(--muted); }
.hint-level b { color: var(--text); }

/* ---------- 练前小灶 ---------- */
.primer { padding: 0; overflow: hidden; }
.primer-head {
  display: flex; align-items: center; gap: 8px; width: 100%; text-align: left;
  background: var(--accent-soft); border: none; padding: 14px 20px; cursor: pointer;
  font-size: 14.5px; color: var(--text); border-radius: 14px 14px 0 0;
}
.primer-head b { font-weight: 600; }
.primer-caret { color: var(--primary); font-size: 12px; transition: transform 0.18s; }
.primer-caret.open { transform: rotate(90deg); }
.primer-body { padding: 16px 20px; display: flex; flex-direction: column; gap: 14px; }
.primer-item { display: flex; flex-direction: column; gap: 3px; }
.primer-term { font-family: var(--serif); font-size: 15px; font-weight: 600; display: flex; align-items: center; gap: 9px; }
.primer-tag { font-size: 11.5px; font-weight: 500; padding: 1px 8px; border-radius: 999px; font-family: 'Segoe UI', sans-serif; }
.primer-tag.done { background: #e4ede0; color: #3f5837; }
.primer-tag.new { background: var(--accent-soft); color: var(--primary-dark); }
.primer-desc { font-size: 13.5px; color: var(--muted); line-height: 1.65; }
.primer-foot { margin: 4px 0 0; font-size: 12.5px; color: var(--muted); }
.primer-sub { font-size: 13px; font-weight: 600; color: var(--text); margin-top: 2px; }

/* 代码符号扫盲 */
.syntax-box { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.syntax-head {
  display: flex; align-items: center; gap: 7px; width: 100%; text-align: left;
  background: var(--bg); border: none; padding: 10px 14px; cursor: pointer;
  font-size: 13.5px; color: var(--text);
}
.syntax-list { padding: 6px 14px 12px; display: flex; flex-direction: column; gap: 9px; }
.syntax-item { display: flex; flex-direction: column; gap: 2px; }
.syntax-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.syntax-name {
  font-family: Consolas, monospace; font-size: 13px; font-weight: 700; color: var(--primary-dark);
}
.syntax-desc { font-size: 13px; color: var(--muted); line-height: 1.6; }
.brick-known {
  flex-shrink: 0; font-size: 11.5px; color: var(--muted); border: 1px solid var(--border);
  background: none; padding: 1px 8px; border-radius: 999px;
}
.brick-known:hover { border-color: var(--green); color: var(--green); }
.brick-hidden { font-size: 12px; color: var(--muted); margin: 6px 0 0; }
.brick-allknown { font-size: 12px; color: var(--muted); margin: 4px 0; }
.brick-toggle { font-size: 12px; color: var(--muted); background: none; border: none; padding: 0; cursor: pointer; }
.brick-toggle:hover { color: var(--text); }
.hidden-list { margin-top: 6px; display: flex; flex-direction: column; gap: 5px; }
.hidden-item { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.brick-restore { font-size: 12px; color: var(--primary); background: none; border: 1px solid var(--border); border-radius: 6px; padding: 1px 8px; cursor: pointer; }
.brick-restore:hover { border-color: var(--primary); }
.brick-reset { font-size: 12px; color: var(--primary); background: none; border: none; padding: 2px 0 0; cursor: pointer; align-self: flex-start; }

/* 逐行讲解 */
.walk-btn {
  width: 100%; text-align: left; font-size: 13.5px; color: var(--primary-dark);
  background: var(--accent-soft); border: 1px dashed var(--primary); border-radius: 10px;
  padding: 11px 14px; cursor: pointer;
}
.walk-btn:hover { color: var(--primary); }
.walk-loading { font-size: 13px; color: var(--muted); padding: 8px 2px; }
.walk-rows { display: flex; flex-direction: column; gap: 2px; }
.walk-row {
  display: grid; grid-template-columns: 1fr; gap: 2px;
  padding: 9px 0; border-bottom: 1px dashed var(--border);
}
.walk-row:last-child { border-bottom: none; }
.walk-code {
  font-family: Consolas, monospace; font-size: 13px; color: var(--code-text);
  background: var(--code-bg); border-radius: 6px; padding: 5px 9px; white-space: pre-wrap;
  align-self: start; justify-self: start; max-width: 100%;
}
.walk-exp { font-size: 13.5px; color: var(--text); line-height: 1.7; padding-left: 2px; }
.walk-deep {
  margin-top: 10px; font-size: 13px; color: var(--primary); background: none;
  border: 1px solid var(--border); border-radius: 8px; padding: 6px 12px; cursor: pointer;
}
.walk-deep:hover { border-color: var(--primary); }
.walk-deep-done { margin-top: 10px; font-size: 12px; color: var(--muted); }

/* ---------- 双栏 ---------- */
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; align-items: start; }
@media (max-width: 900px) { .cols { grid-template-columns: 1fr; } }
.panel-title {
  display: flex; justify-content: space-between; align-items: center;
  font-weight: 600; margin-bottom: 14px;
}
.title-text { display: inline-flex; align-items: center; gap: 9px; font-family: var(--serif); font-size: 15.5px; }
.title-sub { font-size: 12px; font-weight: 400; color: var(--muted); }

/* ---------- 代码区 ---------- */
.code {
  width: 100%; height: 420px; resize: vertical;
  background: var(--code-bg); color: var(--code-text);
  font-family: Consolas, 'Courier New', monospace; font-size: 14px;
  line-height: 1.6; border: none; border-radius: 10px; padding: 16px;
  white-space: pre; tab-size: 4;
}
.code:disabled { opacity: 0.78; }
.banner {
  margin-top: 14px; padding: 13px 16px; border-radius: 10px; font-size: 13.5px; line-height: 1.75;
  background: var(--accent-soft); color: #7a3f28;
  border-left: 3px solid var(--primary);
}
.banner b { font-weight: 600; }
.bf-title { font-weight: 600; color: var(--primary-dark); margin-bottom: 4px; }
.bf-body { font-size: 13px; line-height: 1.7; }
.code-actions { display: inline-flex; gap: 8px; }
.run-result {
  margin-top: 12px; border: 1px solid var(--border); border-radius: 10px; overflow: hidden;
}
.run-result-head {
  font-size: 13px; font-weight: 600; padding: 8px 12px; background: var(--bg);
  border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center;
}
.run-result-head.ok { color: var(--green); }
.run-result-head.bad { color: var(--red); }
.run-real { font-size: 11px; font-weight: 400; color: var(--muted); }
.run-block { border-bottom: 1px solid var(--border); }
.run-block:last-child { border-bottom: none; }
.run-label { font-size: 11px; color: var(--muted); padding: 6px 12px 0; font-family: Consolas, monospace; }
.run-out, .run-err {
  margin: 0; padding: 4px 12px 10px; font-family: Consolas, monospace; font-size: 13px;
  line-height: 1.55; white-space: pre-wrap; word-break: break-word;
}
.run-out { color: var(--text); }
.run-err { color: var(--red); }
.run-empty { padding: 10px 12px; font-size: 13px; color: var(--muted); }

/* B0.5 观察卡 */
.obs-card {
  margin-top: 12px; padding: 14px 16px; border-radius: 10px;
  background: var(--accent-soft); border: 1px solid #e0cdbb;
}
.obs-title { font-weight: 600; color: var(--primary-dark); margin-bottom: 4px; }
.obs-hint { font-size: 12.5px; color: var(--muted); margin-bottom: 10px; line-height: 1.6; }
.obs-check { display: block; font-size: 13.5px; margin: 5px 0; cursor: pointer; }
.obs-check input { margin-right: 6px; }
.obs-guess { margin-top: 8px; resize: vertical; }
.obs-actions { display: flex; gap: 10px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
.obs-skip {
  font-size: 13px; color: var(--muted); background: none; border: none;
  text-decoration: underline; padding: 0; cursor: pointer;
}
.obs-skip:hover { color: var(--primary); }
.variant-offer { margin-top: 12px; padding-top: 12px; border-top: 1px solid #e0cdbb; display: flex; flex-direction: column; gap: 8px; }
.variant-label { font-size: 13px; }
.variant-btn { align-self: flex-start; }

/* ---------- 对话区 ---------- */
.tutor-avatar {
  display: inline-flex; align-items: center; justify-content: center;
  width: 27px; height: 27px; border-radius: 8px; font-size: 11px; font-weight: 700;
  background: var(--accent-soft); color: var(--primary-dark); flex-shrink: 0;
}
.chat-panel { display: flex; flex-direction: column; height: 548px; }
.chat { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 14px; padding: 4px 2px; }
.msg { display: flex; align-items: flex-end; gap: 9px; }
.msg.student { justify-content: flex-end; }
.msg .avatar { align-self: flex-start; }
.bubble {
  max-width: 78%; padding: 11px 14px; border-radius: 14px;
  font-size: 14px; line-height: 1.7; white-space: pre-wrap;
}
.msg.tutor .bubble {
  background: #f3eee4; color: var(--text); border-bottom-left-radius: 5px;
}
.msg.student .bubble {
  background: var(--primary); color: #fff; border-bottom-right-radius: 5px;
}
.msg.system { justify-content: center; }
.msg.system .bubble {
  background: transparent; color: var(--muted); font-size: 13px; max-width: 100%;
  border: 1px solid var(--border); border-radius: 10px; text-align: center;
}
.typing { display: inline-flex; gap: 4px; align-items: center; }
.typing span {
  width: 6px; height: 6px; border-radius: 50%; background: var(--primary); opacity: 0.4;
  animation: blink 1.2s infinite both;
}
.typing span:nth-child(2) { animation-delay: 0.2s; }
.typing span:nth-child(3) { animation-delay: 0.4s; }
@keyframes blink { 0%, 60%, 100% { opacity: 0.25; } 30% { opacity: 1; } }

.composer { display: flex; gap: 8px; margin-top: 12px; align-items: flex-end; }
.composer textarea { resize: none; }
.send-btn { align-self: stretch; }
</style>
