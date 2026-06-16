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
const originalCode = ref('')
const codeChanged = computed(() => session.code !== originalCode.value)
const masteredKps = ref(new Set())   // 学生已内化的知识点（练前小灶用来标「已掌握」）
const showPrimer = ref(false)        // 练前小灶默认收起（需要的人再点开），避免页面被撑长
const intervention = ref(null)       // 开题前小检查（命中跨题高频思维默认值才有）；帮手语气、可忽略、本题只首次弹

// 卡住时的小工具：解释默认收起，记住用户偏好；知返始终在思考主线里。
const _panels = JSON.parse(localStorage.getItem('arena_panels') || 'null')
const showExplain = ref(_panels ? !!_panels.explain : false)   // 解释默认关（鼓励先自己读）
function toggleExplain() {
  showExplain.value = !showExplain.value
  localStorage.setItem('arena_panels', JSON.stringify({ explain: showExplain.value, tutor: true }))
}
const showSyntax = ref(false)        // 「代码怎么读」符号扫盲是否展开（默认收起，需要的人点开）
// A+B 空间管理：终端可折叠、思考过程可折叠、逐行讲解做成代码区上滑抽屉
const consoleOpen = ref(true)        // 终端展开/折叠（折叠后只剩状态条）
const thoughtOpen = ref(true)        // 「我的思考过程」四步区展开/折叠
const walkOpen = ref(false)          // 逐行讲解抽屉是否打开（覆盖在代码上）
const walkTall = ref(false)          // 抽屉高度档：false=60% / true=90%
const walkthrough = ref('')          // 逐行讲解文本（点按钮自动生成）
const walkLoading = ref(false)
async function openWalk() {           // 打开抽屉并按需加载讲解
  walkOpen.value = true
  if (!walkthrough.value && !walkLoading.value) await loadWalkthrough(false)
}
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
      thoughtOpen.value = true   // 弹观察卡时确保思考过程是展开的
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
const summaryDraft = ref('')
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
        originalCode.value = d.code
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
    session.patternId = data.pattern_id || patternId   // 智能开题不传 id，用后端选中的
    showPrimer.value = false  // 新关卡练前小灶默认收起，需要的人再点开
    walkthrough.value = ''    // 清掉上一题的逐行讲解
    walkDeep.value = false
    walkOpen.value = false    // 关掉逐行讲解抽屉
    consoleOpen.value = true
    thoughtOpen.value = true
    runResult.value = null
    resetObservation()
    localStorage.setItem('active_session', data.session_id)  // 记下当前关卡，供刷新后续做
    session.code = data.code
    originalCode.value = data.code
    session.task = data.task
    session.stage = '①发现'
    session.hintLevel = 'L0'
    session.fixed = false
    session.done = false
    session.internalizeQuestions = []
    session.variant = null
    messages.value = []
    setIntervention(patternId, data.intervention)
  } catch (e) {
    error.value = e.message
  }
}

// 开题小检查：只在「首次进入该题」时弹一次（localStorage 记住），收起后本题不再弹
function setIntervention(patternId, iv) {
  intervention.value = null
  if (!iv) return
  const seen = JSON.parse(localStorage.getItem('intervention_seen') || '[]')
  if (seen.includes(patternId)) return
  intervention.value = iv
  localStorage.setItem('intervention_seen', JSON.stringify([...seen, patternId]))
}
function dismissIntervention() {
  intervention.value = null
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
const SUMMARY_MARK = '【思考总结】'
const observationPending = ref(false)   // 是否显示观察卡
const observationDone = ref(false)      // 本关是否已观察过（每关首次运行触发一次）
const obsChecks = reactive({ 程序报错了: false, '程序卡住了/跑不完': false, 输出和预期不同: false, 输出正确: false, 我还没看懂: false })
const obsGuess = ref('')

function parseMarkedMessage(mark, labels) {
  const found = messages.value.find((m) => m.role === 'student' && m.text.startsWith(mark))
  if (!found) return null
  const out = {}
  for (const line of found.text.split('\n')) {
    for (const [key, label] of Object.entries(labels)) {
      if (line.startsWith(label)) out[key] = line.slice(label.length).trim()
    }
  }
  return Object.keys(out).length ? out : null
}

const observationRecord = computed(() => {
  const parsed = parseMarkedMessage(OBSERVATION_MARK, { observation: '我观察到：', guess: '我的猜测：' })
  if (parsed) return parsed
  const skipped = messages.value.find((m) =>
    m.role === 'student' && m.text.startsWith(OBSERVATION_MARK) && m.text.includes('暂时描述不出观察'))
  return skipped ? { observation: '当时还没描述出来，请了知返一起看。', guess: null } : null
})
const summaryRecord = computed(() => {
  const marked = parseMarkedMessage(SUMMARY_MARK, { summary: '我想记住：' })
  if (marked) return marked
  if (!session.done) return null
  const lastReflection = [...messages.value].reverse().find((m) =>
    m.role === 'student'
    && !m.text.startsWith(OBSERVATION_MARK)
    && !m.text.startsWith(SUMMARY_MARK)
    && !m.text.startsWith('📤'))
  return lastReflection ? { summary: lastReflection.text } : null
})
const visibleMessages = computed(() => messages.value.filter((m) =>
  !(m.role === 'student' && (m.text.startsWith(OBSERVATION_MARK) || m.text.startsWith(SUMMARY_MARK)))
  && !(m.role === 'system' && m.text.startsWith('运行这段代码，看看它的行为'))))

const verificationNote = computed(() => {
  if (session.done) return '已经完成边界验证，也把这次经验讲清楚了。'
  if (session.fixed || stageIndex(session.stage) >= stageIndex('⑤验证')) {
    return '修复已通过。现在用一个边界输入，说明你预期它会发生什么。'
  }
  if (runResult.value?.timed_out) return '真实运行：程序超时。接下来可以检查循环是否一直在靠近终点。'
  if (runResult.value?.stderr) return '真实运行：程序报错。先用报错信息检查你的猜测。'
  if (runResult.value) return '已经真实运行过一次。结果是否支持你的猜测？'
  return '运行代码、改动后再运行，看看结果是否支持你的猜测。'
})

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

async function submitSummary() {
  const text = summaryDraft.value.trim()
  if (!text || sending.value) return
  summaryDraft.value = ''
  await sendText(`${SUMMARY_MARK}\n我想记住：${text}`)
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
      const ex = d.execution
      if (ex) {
        let resultText = '提交测试未通过'
        if (ex.kind === 'HANG') resultText = '提交测试超时：程序没有在限定时间内结束'
        else if (ex.kind === 'WA') resultText = '提交测试输出不符：实际输出与期望结果不同'
        else if (ex.error_family) {
          resultText = `提交测试运行报错：${ex.error_family}${ex.bug_type ? ` · ${ex.bug_type}` : ''}`
        }
        messages.value.push({ role: 'system', text: resultText })
      }
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

async function runAndCheck() {
  if (running.value || submitting.value || session.fixed) return
  if (codeChanged.value) await submit()
  else await runCurrentCode()
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
        每一关的代码里都藏着一个真实 Bug。你的任务是<b>发现它</b>、和「知返」一起<b>定位它</b>、
        亲手<b>修好它</b>，再讲清楚它为什么会发生——走完六步，知识点才真正属于你。
      </p>
    </div>

    <!-- 智能开一题：不指定题，后端按画像挑你最该补的弱点（系统帮你挑） -->
    <button class="smart-open" @click="start()">
      <span class="smart-open-main">🎲 智能开一题</span>
      <span class="smart-open-sub">让知返按你的画像，挑一道最该补的</span>
    </button>

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
    <!-- 开题前的小检查：帮手语气、非评价、可忽略、本题只首次弹 -->
    <div v-if="intervention" class="precheck">
      <div class="precheck-main">
        <div class="precheck-title">💡 开题前的小检查</div>
        <div class="precheck-body">这类题里，先多看一眼：{{ intervention.advice }}</div>
      </div>
      <button class="precheck-close" @click="dismissIntervention" aria-label="收起">×</button>
    </div>

    <div class="stage-bar panel">
      <div class="current-stage">
        <span class="current-stage-label">当前阶段</span>
        <b>{{ session.stage }}</b>
        <span>· {{ session.stage === '③归因' ? '正在弄清为什么出错' :
          session.stage === '④修复' ? '把原因变成自己的修复' :
          session.stage === '⑤验证' ? '检查修复在边界情况是否可靠' :
          session.stage === '⑥内化' ? '把这次经验变成下次的方法' :
          session.stage === '②定位' ? '顺着线索找到可疑位置' : '先看清代码实际发生了什么' }}</span>
      </div>
      <div class="stage-meta">
        <span class="hint-level">提示级别 <b>{{ session.hintLevel }}</b></span>
        <button @click="quit">退出关卡</button>
      </div>
    </div>

    <div class="cols">
      <div class="code-column">
      <div class="panel code-panel">
        <div class="panel-title">
          <span class="title-text">代码</span>
          <span class="code-actions">
            <button class="walk-trigger" @click="openWalk">📖 逐行讲解</button>
            <button class="primary" :disabled="running || submitting || session.fixed" @click="runAndCheck">
              {{ running || submitting ? '运行中…' : '▶ 运行' }}
            </button>
          </span>
        </div>
        <textarea v-show="!walkOpen" v-model="session.code" class="code" spellcheck="false" :disabled="session.fixed" />

        <!-- 逐行讲解：点开就在代码框原位替换显示（每行自带代码=带注解的题目），可下拉、不盖代码 -->
        <div v-if="walkOpen" class="walk-drawer">
          <div class="walk-drawer-bar">
            <span class="walk-drawer-title">逐行讲解</span>
            <button class="wd-btn" @click="walkOpen = false">关闭 ✕</button>
          </div>
          <div class="walk-drawer-body">
            <div v-if="walkLoading" class="walk-loading">知返正在逐行讲解…</div>
            <template v-else-if="walkthrough">
              <div class="walk-rows">
                <div v-for="(r, i) in walkRows" :key="i" class="walk-row">
                  <code v-if="r.code" class="walk-code">{{ r.code }}</code>
                  <div class="walk-exp">{{ r.explain }}</div>
                </div>
              </div>
              <button v-if="!walkDeep" class="walk-deep" @click="loadWalkthrough(true)">还不够懂？再讲细一点 →</button>
              <div v-else class="walk-deep-done">已是最详细的讲法 · 还不懂就把那一行发给知返问</div>
            </template>
            <div v-else class="walk-loading">加载中…</div>
          </div>
        </div>

        <!-- 运行结果：真实运行（路线A，真跑非AI猜），终端样式 + 可折叠（点头部收起，腾纵向空间） -->
        <div v-if="runResult" class="console">
          <button class="console-bar" @click="consoleOpen = !consoleOpen">
            <span class="console-dots"><i></i><i></i><i></i></span>
            <span class="console-title">终端 · 真实运行结果</span>
            <span class="console-status"
                  :class="{ ok: !runResult.stderr && !runResult.timed_out, bad: runResult.stderr || runResult.timed_out }">
              {{ runResult.timed_out ? '⏱ 超时（很可能死循环）' : (runResult.stderr ? '✗ 报错' : '✓ 运行成功') }}
            </span>
            <span class="console-caret">{{ consoleOpen ? '收起 ▲' : '展开 ▼' }}</span>
          </button>
          <div v-show="consoleOpen" class="console-body">
            <div class="console-cmd">$ python main.py</div>
            <pre v-if="runResult.stdout" class="console-out">{{ runResult.stdout }}</pre>
            <pre v-if="runResult.stderr" class="console-err">{{ runResult.stderr }}</pre>
            <div v-if="!runResult.stdout && !runResult.stderr && !runResult.timed_out" class="console-muted">（程序没有任何输出）</div>
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

      <!-- 解释降为代码旁的按需工具，不与思考主线并列。 -->
      <div class="tool-shelf">
        <button :class="['tool-trigger', { open: showExplain }]" @click="toggleExplain">
          <span><b>卡住时的小工具</b> · 认符号、补概念（逐行讲解在代码区右上「📖」）</span>
          <span>{{ showExplain ? '收起 ↑' : '打开 ↓' }}</span>
        </button>
      </div>
      <div v-if="showExplain" class="panel explain-panel">
        <div class="explain-body">
          <!-- 认符号 -->
          <div v-if="visibleBricks.length" class="syntax-box">
            <button class="syntax-head" @click="showSyntax = !showSyntax">
              <span class="primer-caret" :class="{ open: showSyntax }">▸</span>
              先认认这道题里的符号（{{ visibleBricks.length }} 个）
            </button>
            <div v-show="showSyntax" class="syntax-list">
              <div v-for="b in visibleBricks" :key="b.name" class="syntax-item">
                <div class="syntax-row">
                  <span class="syntax-name">{{ b.name }}</span>
                  <button class="brick-known" title="标记懂了，以后不再显示" @click="markBrickLearned(b.name)">✓ 懂了</button>
                </div>
                <span class="syntax-desc">{{ b.desc }}</span>
              </div>
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

          <!-- 概念 -->
          <template v-if="primerConcepts.length">
            <div class="primer-sub">这道题涉及的概念</div>
            <div v-for="c in primerConcepts" :key="c.kp" class="primer-item">
              <div class="primer-term">
                {{ c.kp }}
                <span v-if="c.mastered" class="primer-tag done">已掌握</span>
                <span v-else class="primer-tag new">新</span>
              </div>
              <div class="primer-desc">{{ c.desc || '遇到不懂的随时问知返。' }}</div>
            </div>
          </template>
          <p class="primer-foot">对话里带虚线的词，悬停就能看解释。</p>
        </div>
      </div>
      </div>

      <div class="panel thinking-panel">
        <div class="thinking-head">
          <div>
            <div class="thinking-kicker">这不是作业，写不出来也可以直接问知返</div>
            <h3>我的思考过程</h3>
          </div>
          <span class="thinking-stage">现在 · {{ session.stage.slice(1) }}</span>
          <button class="thought-toggle" @click="thoughtOpen = !thoughtOpen">{{ thoughtOpen ? '收起 ▲' : '展开 ▼' }}</button>
        </div>

        <div v-show="thoughtOpen" class="thought-line">
          <section :class="['thought-step', { active: session.stage === '①发现', filled: observationRecord?.observation }]">
            <span class="thought-dot">1</span>
            <div class="thought-content">
              <div class="thought-title">观察 <span>运行后，实际发生了什么？</span></div>
              <div v-if="observationRecord?.observation" class="thought-note">
                {{ observationRecord.observation }}
              </div>
              <div v-else-if="!observationPending" class="thought-empty">
                点一次“运行并检查”，这里会帮你接住真实结果。
              </div>
              <div v-if="observationPending" class="obs-card">
                <div class="obs-hint">对照左边的真实运行结果，随手勾一勾。可以留空，也可以直接请知返一起看。</div>
                <div class="obs-options">
                  <label v-for="(_, k) in obsChecks" :key="k" class="obs-check">
                    <input type="checkbox" v-model="obsChecks[k]" /> {{ k }}
                  </label>
                </div>
              </div>
            </div>
          </section>

          <section :class="['thought-step', { active: ['②定位', '③归因', '④修复'].includes(session.stage), filled: observationRecord?.guess }]">
            <span class="thought-dot">2</span>
            <div class="thought-content">
              <div class="thought-title">猜测 <span>问题可能在哪里，为什么？</span></div>
              <div v-if="observationRecord?.guess" class="thought-note">
                {{ observationRecord.guess }}
              </div>
              <template v-else-if="observationPending">
                <textarea v-model="obsGuess" class="obs-guess" rows="2"
                          placeholder="问题可能出在……（说不上来可以留空）" />
                <div class="obs-actions">
                  <button class="primary" :disabled="sending" @click="submitObservation">记下来，再听知返怎么想 →</button>
                  <button class="obs-skip" :disabled="sending" @click="skipObservation">我看不懂，直接请知返帮助</button>
                </div>
              </template>
              <div v-else class="thought-empty">先凭感觉也可以，知返会陪你把猜测一点点变清楚。</div>
            </div>
          </section>

          <section :class="['thought-step', { active: session.stage === '⑤验证', filled: runResult || session.fixed }]">
            <span class="thought-dot">3</span>
            <div class="thought-content">
              <div class="thought-title">验证 <span>什么结果能支持或推翻猜测？</span></div>
              <div :class="['thought-note', { muted: !runResult && !session.fixed }]">{{ verificationNote }}</div>
            </div>
          </section>

          <section :class="['thought-step', { active: session.stage === '⑥内化', filled: summaryRecord?.summary }]">
            <span class="thought-dot">4</span>
            <div class="thought-content">
              <div class="thought-title">总结 <span>下次再遇到时，我想记住什么？</span></div>
              <div v-if="summaryRecord?.summary" class="thought-note">{{ summaryRecord.summary }}</div>
              <div v-else-if="session.stage === '⑥内化'" class="summary-compose">
                <textarea v-model="summaryDraft" rows="2"
                          placeholder="比如：这个 Bug 为什么发生、我是怎么定位的、下次先检查什么……" />
                <div class="summary-actions">
                  <button class="primary" :disabled="sending || !summaryDraft.trim()" @click="submitSummary">留下这句话</button>
                  <span>也可以不写，直接在下面和知返聊。</span>
                </div>
              </div>
              <div v-else class="thought-empty">走到最后，这里会自然长出一条属于你的经验。</div>
            </div>
          </section>
        </div>

        <div class="tutor-divider">
          <span class="tutor-avatar">返</span>
          <div><b class="tutor-poem">实迷途其未远，觉今是而昨非</b></div>
        </div>
        <div ref="chatBox" class="chat">
          <div v-for="(m, i) in visibleMessages" :key="i" :class="['msg', m.role]">
            <div v-if="m.role === 'tutor'" class="avatar tutor-avatar">知</div>
            <div class="bubble">
              <GlossaryText v-if="m.role !== 'student'" :text="m.text" />
              <template v-else>{{ m.text }}</template>
            </div>
          </div>
          <div v-if="sending" class="msg tutor">
            <div class="avatar tutor-avatar">知</div>
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
/* 智能开一题：系统按画像帮你挑最该补的 */
.smart-open {
  display: flex; flex-direction: column; align-items: flex-start; gap: 3px;
  width: 100%; text-align: left; margin-bottom: 22px; padding: 16px 20px; border-radius: 14px;
  background: var(--accent-soft); border: 1px solid #e0cdbb; cursor: pointer;
  transition: transform 0.18s, box-shadow 0.18s, border-color 0.18s;
}
.smart-open:hover {
  transform: translateY(-2px); border-color: var(--primary); color: inherit;
  box-shadow: 0 14px 30px -16px rgba(193, 95, 60, 0.4);
}
.smart-open-main { font-family: var(--serif); font-size: 17px; font-weight: 600; color: var(--primary-dark); }
.smart-open-sub { font-size: 13px; color: var(--muted); }

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

/* 开题前的小检查：克制的帮手横幅，不告警、不阻断 */
.precheck {
  display: flex; align-items: flex-start; gap: 12px;
  background: var(--accent-soft); border: 1px solid var(--border); border-radius: 12px;
  padding: 12px 14px;
}
.precheck-main { flex: 1; min-width: 0; }
.precheck-title { font-size: 13.5px; font-weight: 600; color: var(--primary-dark); }
.precheck-body { font-size: 13.5px; color: var(--text); line-height: 1.6; margin-top: 3px; }
.precheck-close {
  border: none; background: none; color: var(--muted); font-size: 18px; line-height: 1;
  cursor: pointer; padding: 2px 4px; flex-shrink: 0;
}
.precheck-close:hover { color: var(--text); }

.stage-bar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 16px; padding: 14px 22px; flex-wrap: wrap;
}
.current-stage { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.current-stage-label { color: var(--muted); font-size: 12.5px; }
.current-stage b { font-family: var(--serif); color: var(--primary-dark); font-size: 15px; }
.current-stage > span:last-child { color: var(--muted); font-size: 13px; }
.stepper { display: flex; align-items: center; gap: 0; margin: 0; padding: 0; list-style: none; flex-wrap: wrap; }
.step { display: flex; align-items: center; gap: 6px; color: var(--muted); position: relative; padding-right: 5px; }
.step:not(:last-child)::after {
  content: ''; width: 16px; height: 1px; background: var(--border); margin: 0 7px 0 6px;
}
.step-no {
  display: inline-flex; align-items: center; justify-content: center;
  width: 21px; height: 21px; border-radius: 50%; font-size: 11px; font-weight: 600;
  background: #ece6da; color: var(--muted); transition: all 0.2s;
}
.step-label { font-size: 12.5px; }
.step.active .step-no { background: var(--primary); color: #fff; box-shadow: 0 0 0 3px var(--accent-soft); }
.step.active .step-label { color: var(--text); font-weight: 600; }
.step.done .step-no { background: #cbb9a6; color: #fff; }
.step.done .step-label { color: var(--muted); }
.stage-meta { display: flex; align-items: center; gap: 16px; }
.hint-level { font-size: 13px; color: var(--muted); }
.hint-level b { color: var(--text); }

/* ---------- 练前小灶 ---------- */
/* 辅助层：移到主线下方（CSS order，不动 DOM），折叠条做成安静小条 */
.primer { padding: 0; overflow: hidden; order: 1; }
.primer-head {
  display: flex; align-items: center; gap: 8px; width: 100%; text-align: left;
  background: transparent; border: none; padding: 11px 18px; cursor: pointer;
  font-size: 13.5px; color: var(--muted); border-radius: 14px 14px 0 0;
}
.primer-head b { font-weight: 600; color: var(--text); }
.primer-head-sub { color: var(--muted); font-size: 13px; margin-left: 6px; }
.primer-caret { color: var(--primary); font-size: 12px; transition: transform 0.18s; }
.primer-caret.open { transform: rotate(90deg); }
.primer-body {
  padding: 16px 20px; display: flex; flex-direction: column; gap: 14px;
  max-height: 52vh; overflow-y: auto;   /* 逐行讲解再长也只在本块内滚，不把下面代码/知返顶出屏幕 */
}
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
  width: 100%; text-align: left; font-size: 13.5px; color: var(--muted);
  background: var(--bg); border: 1px solid var(--border); border-radius: 10px;
  padding: 10px 14px; cursor: pointer;
}
.walk-btn:hover { color: var(--primary); border-color: var(--primary); }
.walk-loading { font-size: 13px; color: var(--muted); padding: 8px 2px; }
/* 逐行讲解：搬到代码区那一栏，紧贴代码 */
.code-walk { margin-top: 14px; }
.walk-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.walk-head-title { font-size: 13px; font-weight: 600; color: var(--primary-dark); }
.walk-collapse { font-size: 12px; color: var(--muted); background: none; border: none; cursor: pointer; padding: 2px 4px; }
.walk-collapse:hover { color: var(--primary); }
.walk-rows { display: flex; flex-direction: column; gap: 2px; max-height: 340px; overflow-y: auto; }
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

/* ---------- 认知过程双栏 ---------- */
.cols {
  display: grid; grid-template-columns: minmax(0, 44fr) minmax(390px, 56fr);
  gap: 20px; align-items: start;   /* 代码栏不再被拉伸去对齐右边，终端紧跟代码、无大空隙 */
}
.code-column { min-width: 0; display: flex; flex-direction: column; gap: 12px; }
.code-panel { display: flex; flex-direction: column; }
.explain-panel { max-height: 560px; overflow-y: auto; }
.explain-body { display: flex; flex-direction: column; gap: 14px; }
.tool-shelf { padding: 0 4px; }
.tool-trigger {
  display: flex; justify-content: space-between; align-items: center; gap: 16px;
  width: 100%; padding: 9px 12px; border: 1px solid transparent; background: transparent;
  color: var(--muted); text-align: left; font-size: 12.5px; border-radius: 9px;
}
.tool-trigger b { color: var(--text); font-weight: 600; }
.tool-trigger:hover, .tool-trigger.open {
  background: #f1ebe0; border-color: var(--border); color: var(--primary);
}
@media (max-width: 900px) {
  .cols { grid-template-columns: 1fr; }
  .thinking-panel { min-height: auto; }
}
/* 手机端细节 */
@media (max-width: 640px) {
  .cols { gap: 14px; }
  .lobby-hero h2 { font-size: 23px; }
  .hint { font-size: 14px; }
  .rec-card { flex-direction: column; align-items: flex-start; gap: 10px; padding: 14px 16px; }
  .rec-cta { align-self: flex-end; }
  .stage-bar { padding: 12px 14px; }
  .code { min-height: 220px; flex: 1 1 220px; font-size: 14px; padding: 14px; }
  .console-body { max-height: 220px; }
  .explain-panel { max-height: none; }   /* 单列时不要再套一层内滚 */
  .composer { flex-direction: column; align-items: stretch; }
  .send-btn { width: 100%; }
}
.panel-title {
  display: flex; justify-content: space-between; align-items: center; gap: 10px;
  flex-wrap: wrap; font-weight: 600; margin-bottom: 14px;
}
.title-text { display: inline-flex; align-items: center; gap: 9px; font-family: var(--serif); font-size: 15.5px; white-space: nowrap; }
.title-sub { font-size: 12px; font-weight: 400; color: var(--muted); }

/* ---------- 代码区 ---------- */
.code {
  width: 100%; height: 360px; resize: none; overflow: auto;
  background: #f5f0e6; color: var(--text);
  font-family: Consolas, 'Courier New', monospace; font-size: 14.5px;
  line-height: 1.75; border: 1px solid #d8d0bf; border-radius: 10px; padding: 16px 18px;
  box-shadow: inset 0 1px 0 #fffdf8, 0 2px 8px rgba(43,41,36,0.06);
  white-space: pre-wrap; word-break: break-word; tab-size: 4;
  scrollbar-width: none; -ms-overflow-style: none;   /* 可滚动但隐藏滚动条（仍可滚轮/拖动/键盘） */
}
.code::-webkit-scrollbar { display: none; }
.code:focus { outline: 2px solid var(--accent-soft); border-color: var(--primary); }
.code:disabled { opacity: 0.85; background: #efe9dc; }
.banner {
  margin-top: 14px; padding: 13px 16px; border-radius: 10px; font-size: 13.5px; line-height: 1.75;
  background: var(--accent-soft); color: #7a3f28;
  border-left: 3px solid var(--primary);
}
.banner b { font-weight: 600; }
.bf-title { font-weight: 600; color: var(--primary-dark); margin-bottom: 4px; }
.bf-body { font-size: 13px; line-height: 1.7; }
.code-actions { display: inline-flex; gap: 8px; flex-shrink: 0; }
.code-actions button { white-space: nowrap; }
/* 提交修复=克制次按钮（运行才是该先点的、温暖主按钮），降低"被评判"压力 */
.submit-btn { color: var(--muted); }
.submit-btn:hover:not(:disabled) { color: var(--primary); border-color: var(--primary); }
/* 运行结果 = 正式终端：深色控制台，和浅色代码编辑区分工清楚 */
.console {
  margin-top: 14px; border-radius: 10px; overflow: hidden; background: #1e1c1a;
  border: 1px solid #14120f; box-shadow: 0 3px 12px rgba(20,18,15,0.18);
  font-family: Consolas, 'Courier New', monospace;
}
.console-bar { display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 12px;
  background: #2b2924; border: none; border-radius: 0; cursor: pointer; text-align: left; }
.console-bar:hover { background: #332f2a; }
.console-caret { font-size: 11px; color: #b9b0a0; margin-left: 10px; flex-shrink: 0; }
.console-dots { display: inline-flex; gap: 6px; }
.console-dots i { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.console-dots i:nth-child(1) { background: #e06c5a; }
.console-dots i:nth-child(2) { background: #e3b341; }
.console-dots i:nth-child(3) { background: #6fae5f; }
.console-title { color: #b9b0a0; font-size: 12px; letter-spacing: 0.3px; }
.console-status { margin-left: auto; font-size: 12px; font-weight: 600; }
.console-status.ok { color: #8fc97e; }
.console-status.bad { color: #f0907f; }
.console-body { padding: 12px 14px; font-size: 13px; line-height: 1.6; max-height: 300px; overflow: auto; }

/* 逐行讲解触发按钮（代码区右上） */
.walk-trigger { font-size: 13px; padding: 6px 12px; }
/* 逐行讲解抽屉：从代码区底部上滑、覆盖代码下部，不撑高页面 */
/* 逐行讲解：就地替换代码框（不浮层、不盖代码、可滚动） */
.walk-drawer {
  display: flex; flex-direction: column; height: 360px;
  background: var(--panel); border: 1px solid var(--border); border-radius: 10px; overflow: hidden;
}
.walk-drawer-bar {
  display: flex; align-items: center; justify-content: space-between; flex-shrink: 0;
  padding: 8px 14px; background: var(--accent-soft); border-bottom: 1px solid var(--border);
}
.walk-drawer-title { font-weight: 600; font-size: 14px; color: var(--primary-dark); }
.walk-drawer-actions { display: inline-flex; gap: 6px; }
.wd-btn { font-size: 12px; padding: 2px 8px; border: none; background: none; color: var(--muted); white-space: nowrap; }
.wd-btn:hover { color: var(--primary); }
.walk-drawer-body { flex: 1; overflow-y: auto; padding: 12px 14px; }
.walk-drawer .walk-rows { max-height: none; overflow: visible; }
/* 思考过程折叠开关 */
.thought-toggle { font-size: 12px; padding: 3px 10px; border-radius: 7px; color: var(--muted); margin-left: 8px; flex-shrink: 0; }
.thought-toggle:hover { color: var(--primary); border-color: var(--primary); }
.console-cmd { color: #7e7668; margin-bottom: 6px; }
.console-out { margin: 0; white-space: pre-wrap; word-break: break-word; color: #e6e0d4; }
.console-err { margin: 4px 0 0; white-space: pre-wrap; word-break: break-word; color: #f0907f; }
.console-muted { color: #7e7668; }

/* B0.5 观察卡：嵌在思考线上，不做弹窗式任务。 */
.obs-card {
  margin-top: 8px; padding: 10px 12px; border-radius: 9px;
  background: #f7f1e8; border: 1px solid #e6d8c8;
}
.obs-hint { font-size: 12.5px; color: var(--muted); margin-bottom: 8px; line-height: 1.6; }
.obs-options { display: flex; gap: 6px 12px; flex-wrap: wrap; }
.obs-check { display: inline-flex; align-items: center; font-size: 12.5px; cursor: pointer; }
.obs-check input { margin-right: 6px; }
.obs-guess { margin-top: 8px; resize: vertical; background: #fffdf9; }
.obs-actions { display: flex; gap: 10px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
.obs-actions .primary { font-size: 12.5px; padding: 7px 12px; }
.obs-skip {
  font-size: 12.5px; color: var(--muted); background: none; border: none;
  text-decoration: underline; padding: 0; cursor: pointer;
}
.obs-skip:hover { color: var(--primary); }
.variant-offer { margin-top: 12px; padding-top: 12px; border-top: 1px solid #e0cdbb; display: flex; flex-direction: column; gap: 8px; }
.variant-label { font-size: 13px; }
.variant-btn { align-self: flex-start; }

/* ---------- 思考主线 + 知返 ---------- */
.thinking-panel {
  min-height: 650px; height: 100%; padding: 22px 24px; display: flex; flex-direction: column;
  box-shadow: 0 8px 28px -24px rgba(86, 55, 38, 0.45);
}
.thinking-head {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 16px;
  padding-bottom: 18px; border-bottom: 1px solid var(--border);
}
.thinking-kicker { color: var(--muted); font-size: 12px; line-height: 1.5; margin-bottom: 4px; }
.thinking-head h3 {
  margin: 0; font-family: var(--serif); font-size: 21px; font-weight: 600;
}
.thinking-stage {
  flex-shrink: 0; margin-left: auto; padding: 4px 10px; border-radius: 999px;
  color: var(--primary-dark); background: var(--accent-soft); font-size: 12px;
}
.thought-line { padding: 18px 0 2px; }
.thought-step {
  display: grid; grid-template-columns: 30px minmax(0, 1fr); gap: 12px;
  position: relative; padding-bottom: 18px;
}
.thought-step:not(:last-child)::before {
  content: ''; position: absolute; left: 14px; top: 29px; bottom: -1px;
  width: 1px; background: #ded2c2;
}
.thought-dot {
  position: relative; z-index: 1; display: inline-flex; align-items: center; justify-content: center;
  width: 29px; height: 29px; border-radius: 50%; background: #eee8dd;
  color: var(--muted); font-family: var(--serif); font-size: 12px;
  border: 1px solid #e0d6c8;
}
.thought-step.active .thought-dot {
  background: var(--primary); border-color: var(--primary); color: #fff;
  box-shadow: 0 0 0 4px var(--accent-soft);
}
.thought-step.filled:not(.active) .thought-dot { background: #dfc7b8; color: #70422f; }
.thought-content { min-width: 0; padding-top: 3px; }
.thought-title {
  font-family: var(--serif); font-size: 15px; font-weight: 600; color: var(--text);
}
.thought-title span {
  margin-left: 7px; color: var(--muted); font-family: 'Segoe UI', sans-serif;
  font-size: 12px; font-weight: 400;
}
.thought-note {
  margin-top: 7px; padding: 9px 11px; background: #f7f2e9;
  border-left: 2px solid #d6aa91; border-radius: 0 8px 8px 0;
  color: var(--text); font-size: 13px; line-height: 1.65; white-space: pre-wrap;
}
.thought-note.muted, .thought-empty {
  margin-top: 6px; color: var(--muted); font-size: 12.5px; line-height: 1.6;
}
.summary-compose { margin-top: 8px; }
.summary-compose textarea { resize: vertical; background: #fffdf9; }
.summary-actions { display: flex; align-items: center; gap: 10px; margin-top: 8px; flex-wrap: wrap; }
.summary-actions button { font-size: 12.5px; padding: 7px 12px; }
.summary-actions span { color: var(--muted); font-size: 12px; }
.tutor-divider {
  display: flex; align-items: center; gap: 10px; padding: 16px 0 12px;
  border-top: 1px solid var(--border);
}
.tutor-divider div { display: flex; align-items: baseline; gap: 9px; flex-wrap: wrap; min-width: 0; }
.tutor-divider b { font-family: var(--serif); font-size: 15px; }
.tutor-divider span:not(.tutor-avatar) { color: var(--muted); font-size: 12px; }
.tutor-avatar {
  display: inline-flex; align-items: center; justify-content: center;
  width: 27px; height: 27px; border-radius: 8px; font-size: 14px; font-weight: 700;
  font-family: var(--serif); background: var(--accent-soft); color: var(--primary-dark); flex-shrink: 0;
}
.tutor-logo { color: var(--primary); }
.tutor-logo svg { width: 17px; height: 17px; }
.tutor-poem { font-family: var(--serif); font-size: 14.5px; color: var(--text); }
.chat {
  min-height: 380px; flex: 1 1 380px; overflow-y: auto; display: flex; flex-direction: column;
  gap: 12px; padding: 4px 3px 8px;
}
.msg { display: flex; align-items: flex-end; gap: 9px; }
.msg.student { justify-content: flex-end; }
.msg .avatar { align-self: flex-start; }
.bubble {
  max-width: 88%; padding: 11px 14px; border-radius: 14px;
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
