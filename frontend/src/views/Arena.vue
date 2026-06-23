<script setup>
import { onMounted, reactive, ref, computed, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, getStudentId } from '../api'
import GlossaryText from '../components/GlossaryText.vue'
import { GLOSSARY, bricksInCode } from '../glossary'

const route = useRoute()
const router = useRouter()

const STAGES = ['①发现', '②定位', '③归因', '④修复', '⑤验证', '⑥内化']
function stageIndex(s) { return STAGES.indexOf(s) }


const patterns = ref([])         // 题库（仅供做题页「练前小灶」按 pattern_id 查知识点；大厅不再铺题库）
const activeSessions = ref([])   // 未完成关卡（接着做）；后端 active-sessions 是唯一真相，按活跃度倒序，第一条置顶高亮
const abandoning = ref(null)     // 正在二次确认「放弃」的 session_id（null=没有确认框）
const archiveOpen = ref(false)   // 档案面板（未完成关卡）是否打开——大厅「接着做」文字按钮触发
const session = reactive({
  id: null, patternId: null, code: '', task: '', stage: '①发现', hintLevel: 'L0',
  fixed: false,      // 代码已通过测试（进入⑤验证），但本关尚未结束
  done: false,       // ⑥内化判定通过，本关结束
  internalizeQuestions: [],
  variant: null,     // 内化通过后推荐的变式题（迁移检验）
})
const originalCode = ref('')
const codeChanged = computed(() => session.code !== originalCode.value)
// 灵犀感知层（设计 11）：从现成信号推一句「读过你」的招呼，至多一条；无信号返回 null。
// 纯派生、只读、不追问、不诊断、给选择留出口。给出选择、不下判断。
const presence = ref(null)   // 后端最近活跃时间 {has_history, days_since}
const presenceHint = computed(() => {
  const list = activeSessions.value
  if (!list.length) {
    // 无未完成关卡：用最近活跃时间，温柔接住「久别回来 / 新朋友」（补全 doc11 缺口）
    const p = presence.value
    if (!p) return null
    if (!p.has_history) return '欢迎，第一次来——点上面「智能开一题」，我陪你从一道轻松的开始。'
    if (p.days_since != null && p.days_since >= 7) return '好久不见，不急，今天可以先从一道轻一点的开始。'
    return null   // 最近来过、又没有未完成题：不硬塞（灵犀铁律：不命中则不出）
  }
  const top = list[0]
  const gapDays = Math.floor((Date.now() - new Date(top.last_active_at).getTime()) / 86400000)
  if (Number.isNaN(gapDays)) return '我还记得你上次停在这里，但要不要继续，由你决定。'
  if (gapDays >= 7) return '好久不见，不急，今天可以先开一道轻一点的。'
  const highStages = ['③归因', '④修复', '⑤验证']
  if (gapDays >= 2 && highStages.includes(top.stage)) {
    return `上次那道你在${top.stage.slice(1)}阶段停了挺久，今天可以接着收尾，也可以先换一道轻松的。`
  }
  return '我还记得你上次停在这里，但要不要继续，由你决定。'
})
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

// 灵犀挫败台阶（设计 11）：做题里「改了代码还连续报错」时飘一句软提示、几秒自退。
// 两道节流：①跨题——每天至多飘一次（绝不每道题都弹）②门槛——重复点同一份报错不算，
// 必须"改了再运行还错"才算一次真挣扎。纯前端、读人不追问、给选择不诊断；不动知返、不碰判题。
const LINGXI_DAY_KEY = 'lingxi_last_shown'
const consecutiveStruggles = ref(0)   // 「改了代码却还报错」的连续次数
const lingxiBubble = ref('')
let lastErrorCode = null              // 上次报错时的代码，用来识别"重复点同一份"
function resetLingxi() { consecutiveStruggles.value = 0; lastErrorCode = null; lingxiBubble.value = '' }
function maybeShowLingxi() {
  // 门槛=3：报错→改→还错→再改→还错（改了两次都没成）才算真卡住。对零基础，
  // "改一次还错"太正常，不该当挫败；等真的反复试都没成，才轻轻递一句。
  if (consecutiveStruggles.value < 3) return
  const today = new Date().toISOString().slice(0, 10)
  if (localStorage.getItem(LINGXI_DAY_KEY) === today) return   // 今天已飘过 → 安静一整天
  lingxiBubble.value = '接连改了又没过也没关系，挺正常的~ 把报错发给知返一起看，或者先歇口气，不急。'
  localStorage.setItem(LINGXI_DAY_KEY, today)
  setTimeout(() => { lingxiBubble.value = '' }, 5500)   // 停 5.5 秒，自己淡出
}
watch(runResult, (r) => {
  if (!r) return                                        // 改代码清空结果时不计
  if (r.stderr || r.timed_out) {
    if (session.code !== lastErrorCode) {               // 改了代码还报错=一次真挣扎；重复点同一份不算
      consecutiveStruggles.value++
      lastErrorCode = session.code
    }
  } else {
    consecutiveStruggles.value = 0                      // 跑通了，挣扎清零
    lastErrorCode = null
  }
  maybeShowLingxi()
})

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

const studentId = getStudentId()   // 做题页浅色顶栏显示

// 浅色代码编辑器：行号 + 语法高亮叠加层（透明 textarea 在上、高亮 pre 在下、滚动同步）
const taEl = ref(null)
const hlEl = ref(null)
const gutterEl = ref(null)
const codeLineCount = computed(() => (session.code || '').split('\n').length)
function _escHtml(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') }
function highlightPython(src) {
  return _escHtml(src || '').replace(
    /(#[^\n]*)|('[^'\n]*'|"[^"\n]*")|\b(def|return|for|in|if|elif|else|while|and|or|not|None|True|False|import|from|class|with|as|pass|break|continue|lambda|yield|try|except|finally|raise|is|assert|del)\b|\b(print|range|len|int|str|list|dict|set|tuple|float|sum|max|min|abs|enumerate|zip|map|filter|sorted|input|open|append|round)\b|\b(\d+\.?\d*)\b/g,
    (m, com, str, kw, bi, num) =>
      com ? `<span class="t-com">${com}</span>`
        : str ? `<span class="t-str">${str}</span>`
        : kw ? `<span class="t-kw">${kw}</span>`
        : bi ? `<span class="t-bi">${bi}</span>`
        : num ? `<span class="t-num">${num}</span>` : m,
  )
}
const highlightedCode = computed(() => highlightPython(session.code))
function syncScroll() {
  const ta = taEl.value
  if (!ta) return
  if (hlEl.value) { hlEl.value.scrollTop = ta.scrollTop; hlEl.value.scrollLeft = ta.scrollLeft }
  if (gutterEl.value) gutterEl.value.scrollTop = ta.scrollTop
}
const termHint = computed(() => {
  const r = runResult.value
  if (!r || r.timed_out) return ''
  if (r.stderr) { const last = (r.stderr.trim().split('\n').pop() || '').slice(0, 40); return last ? ' · ' + last : '' }
  if (r.stdout) { const first = (r.stdout.trim().split('\n')[0] || '').slice(0, 28); return first ? ' · 输出 ' + first : '' }
  return ''
})

// 单焦点：点代码行/行号 → 滑出那一行的讲解（内容用现成「逐行讲解」walkRows，不泄雷位置）
const selectedLine = ref(null)
function showLine(n) {
  selectedLine.value = n
  if (!walkthrough.value && !walkLoading.value) loadWalkthrough(false)
}
function clickLine(n) {           // 点行号：滑出该行讲解；点同一行可收起
  if (selectedLine.value === n) { selectedLine.value = null; return }
  showLine(n)
}
const lineNote = computed(() => {
  if (!selectedLine.value) return ''
  if (walkLoading.value) return '知返正在生成逐行讲解…'
  const r = (walkRows.value || [])[selectedLine.value - 1]
  return r?.explain || '这一行还没有讲解——点「运行」看真实结果，或在右边问知返。'
})

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
  } catch (e) {
    error.value = '无法连接后端：' + e.message
  }
  loadMastered()
  // 从能力画像「做变式巩固」跳来：自动开始指定关卡（优先于续做）
  if (route.query.start) {
    const pid = String(route.query.start)
    const mode = route.query.mode === 'review' ? 'review' : 'debug'
    router.replace({ query: {} })  // 清掉 query，避免刷新重复触发
    start(pid, mode)
    return
  }
  // 接着做：列出所有未完成关卡让用户自选，不再静默自动跳（设计 08）。
  // 后端 active-sessions 是唯一真相；localStorage 单会话恢复机制已退役。
  loadActiveSessions()
  loadPresence()
})

async function loadActiveSessions() {
  try {
    const d = await api.getActiveSessions()
    activeSessions.value = d.sessions || []
  } catch (e) {
    activeSessions.value = []   // 拿不到就不显示「接着做」，不阻塞大厅
  }
}

async function loadPresence() {
  try {
    presence.value = await api.getPresence()
  } catch (e) { /* 拿不到就不出久别招呼，不阻塞大厅 */ }
}

// 「接着做」卡上的活跃时间：刚刚 / N 分钟前 / N 小时前 / N 天前
function relTime(ts) {
  if (!ts) return ''
  const then = new Date(ts).getTime()
  if (Number.isNaN(then)) return ''
  const mins = Math.floor((Date.now() - then) / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs} 小时前`
  return `${Math.floor(hrs / 24)} 天前`
}

// 显式点击续做某关：拉会话、灌入状态，从静默自动恢复改为用户主动触发
async function resume(sessionId) {
  error.value = ''
  archiveOpen.value = false   // 进题前关掉档案面板，避免退出回大厅时它还开着
  try {
    const d = await api.getSession(sessionId)
    if (d.status !== 'active') {   // 已被别处结束/放弃 → 刷新列表
      await loadActiveSessions()
      return
    }
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
    resetLingxi()
    messages.value = d.messages
    messages.value.push({ role: 'system', text: '已回到这道题，接着来吧。' })
  } catch (e) {
    error.value = '无法恢复这道题：' + e.message
  }
}

// 放弃一道未完成关卡：二次确认后置 abandoned（不删历史/事件流），从列表移除
async function abandon(sessionId) {
  try {
    await api.abandonSession(sessionId)
    activeSessions.value = activeSessions.value.filter((s) => s.session_id !== sessionId)
  } catch (e) {
    error.value = '放弃失败：' + e.message
  } finally {
    abandoning.value = null
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

async function start(patternId, mode = 'debug') {
  error.value = ''
  try {
    const data = await api.createSession(patternId, mode)
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
    resetLingxi()
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
    // 复习模式：温和区分开场，提醒这是回看老题（不重弹开题干预）
    if (mode === 'review') {
      messages.value.push({ role: 'system',
        text: '🔁 复习模式：我们回头看看这道老题。还记得当时它为什么会出问题吗？先运行一下，凭记忆找找那个雷。' })
    } else {
      setIntervention(patternId, data.intervention)
    }
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
  // 退出回大厅：会话在后端仍是 active（未放弃），会重新出现在「接着做」里。
  session.id = null
  messages.value = []
  loadActiveSessions() // 刚退出的这道题会回到「接着做」列表
}
</script>

<template>
  <div v-if="error" class="panel error">{{ error }}</div>

  <!-- 选题 -->
  <div v-if="!session.id" class="lobby">
    <div class="lobby-hero">
      <h2 class="lobby-title">
        Bug 闯关训练场
        <!-- 接着做：稳定文字按钮（不用图标库/SVG，避免渲染成空白方块），点开档案面板 -->
        <button
          v-if="activeSessions.length"
          class="archive-btn"
          title="接着做"
          aria-label="接着做"
          @click="archiveOpen = true"
        >接着做</button>
      </h2>
      <p class="lobby-sub">和「知返」一起发现、定位、修好代码里的真实 Bug。</p>
    </div>

    <!-- 灵犀感知层（设计 11）：一句「读过你」的招呼，推理不追问、给选择留出口、命中才出现 -->
    <p v-if="presenceHint" class="presence">{{ presenceHint }}</p>

    <!-- 主角：开一道新题（不指定题，后端按画像/随机挑）。大厅唯一焦点。 -->
    <button class="smart-open hero" @click="start()">
      <span class="smart-open-main">智能开一题</span>
      <span class="smart-open-sub">让知返按你的画像，挑一道最该补的</span>
    </button>

    <!-- 安静入口：推荐与题库搬去能力画像（IA 见 doc 10，落地下一轮），这里先指过去 -->
    <RouterLink :to="{ path: '/profile', query: { tab: '推荐' } }" class="browse-link">查看推荐与题库 →</RouterLink>

    <!-- 档案面板：未完成关卡（接着做）。点标题旁「接着做」按钮打开。复用 resume/abandon，不改逻辑。 -->
    <div v-if="archiveOpen" class="archive-overlay" @click.self="archiveOpen = false">
      <div class="archive-panel">
        <div class="archive-head">
          <h3>接着做</h3>
          <button class="archive-close" aria-label="关闭" @click="archiveOpen = false">×</button>
        </div>
        <p class="archive-sub">没做完的题都在这儿，想接着做随时回来。</p>
        <div v-for="s in activeSessions" :key="s.session_id" class="resume-card">
          <div class="resume-info">
            <span class="resume-name">{{ s.name }}</span>
            <span class="resume-stage">上次停在：{{ s.stage }}</span>
            <span class="resume-time">{{ relTime(s.last_active_at) }}</span>
          </div>
          <div v-if="abandoning !== s.session_id" class="resume-actions">
            <button class="resume-go" @click="resume(s.session_id)">继续 →</button>
            <button class="resume-drop" @click="abandoning = s.session_id">放弃</button>
          </div>
          <div v-else class="resume-confirm">
            <span>放弃后不会删除你的学习记录，只是不再出现在「接着做」里。确认放弃吗？</span>
            <div class="resume-confirm-btns">
              <button class="resume-drop-yes" @click="abandon(s.session_id)">放弃</button>
              <button class="resume-keep" @click="abandoning = null">算了，继续做</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- 做题 -->
  <div v-else class="ws">
   <div class="ws-card">
    <!-- 浅色顶栏（做题页全屏接管为暖纸卡片；盖住共享顶栏，不影响其它页） -->
    <div class="wt">
      <div class="wt-brand"><span class="wt-logo">知</span> ACP Learning</div>
      <nav class="wt-nav">
        <RouterLink to="/arena" class="wt-on">Bug 闯关</RouterLink>
        <RouterLink to="/timeline">成长轨迹</RouterLink>
        <RouterLink to="/profile">能力画像</RouterLink>
      </nav>
      <span class="wt-id">{{ studentId }}</span>
      <button class="wt-quit" @click="quit">退出关卡</button>
    </div>

    <!-- 灵犀挫败台阶：连续报错时飘一句软提示，几秒自退（设计 11） -->
    <transition name="lingxi-fade">
      <div v-if="lingxiBubble" class="lingxi-bubble">
        <span class="lingxi-emoji">💭</span>
        <span class="lingxi-text">{{ lingxiBubble }}</span>
      </div>
    </transition>

    <div class="wb">
      <div class="wl">
        <!-- 代码卡（暖纸） -->
        <div class="cc">
          <div class="cc-bar">
            <span class="cc-tab">main.py</span>
            <button class="cc-run" :disabled="running || submitting || session.fixed" @click="runAndCheck">
              {{ running || submitting ? '运行中…' : '▶ 运行' }}
            </button>
          </div>
          <div class="cc-edit">
            <div ref="gutterEl" class="cc-gutter">
              <div v-for="n in codeLineCount" :key="n" :class="{ on: selectedLine === n }" @click="clickLine(n)">{{ n }}</div>
            </div>
            <div class="cc-wrap">
              <div v-if="selectedLine" class="cc-band" :style="{ top: (16 + (selectedLine - 1) * 31) + 'px' }" />
              <pre ref="hlEl" class="cc-hl" aria-hidden="true"><code v-html="highlightedCode" /></pre>
              <textarea ref="taEl" v-model="session.code" class="cc-ta" spellcheck="false"
                        :disabled="session.fixed" @scroll="syncScroll" />
            </div>
            <!-- 滑出讲解便签：点行号触发，内容用现成「逐行讲解」(walkRows)；不泄雷 -->
            <div v-if="selectedLine" class="cc-note" :style="{ top: Math.max(8, (16 + (selectedLine - 1) * 31) - 6) + 'px' }">
              <div class="cc-note-head">
                <span class="cc-note-line">第 {{ selectedLine }} 行</span>
                <button class="cc-note-x" @click="selectedLine = null" aria-label="收起">×</button>
              </div>
              <div class="cc-note-body">{{ lineNote }}</div>
            </div>
          </div>

          <!-- 终端状态条（默认一行，运行后可展开） -->
          <div class="cc-term">
            <button class="cc-term-bar" @click="runResult && (consoleOpen = !consoleOpen)">
              <span class="cc-dots"><i /><i /><i /></span>
              <span class="cc-term-title">终端</span>
              <span class="cc-term-s" :class="{ bad: runResult && (runResult.stderr || runResult.timed_out) }">{{ runResult ? ((runResult.timed_out ? '超时 · 很可能死循环' : (runResult.stderr ? '运行报错' : '运行成功')) + termHint) : '还没运行 · 点「运行」看真实结果' }}</span>
              <span v-if="runResult" class="cc-term-c">{{ consoleOpen ? '收起 ▾' : '展开 ▾' }}</span>
            </button>
            <div v-if="runResult" v-show="consoleOpen" class="cc-term-body">
              <pre v-if="runResult.stdout" class="console-out">{{ runResult.stdout }}</pre>
              <pre v-if="runResult.stderr" class="console-err">{{ runResult.stderr }}</pre>
              <div v-if="!runResult.stdout && !runResult.stderr && !runResult.timed_out" class="console-muted">（程序没有任何输出）</div>
            </div>
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
          ✓ 代码修对了——接着到右边和知返走完<b>验证</b>、<b>内化</b>，这关才算真学会。
        </div>

        <!-- 逐行讲解抽屉（完整通读；点行号是即时单行讲解） -->
        <div v-if="walkOpen" :class="['walk-drawer', { tall: walkTall }]">
          <div class="walk-drawer-bar">
            <span class="walk-drawer-title">逐行讲解</span>
            <span class="walk-drawer-actions">
              <button class="wd-btn" @click="walkTall = !walkTall">{{ walkTall ? '收矮' : '加高' }}</button>
              <button class="wd-btn" @click="walkOpen = false">✕</button>
            </span>
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

      <!-- 看不懂代码?：合并 逐行讲解 + 认符号 + 补概念 -->
      <div class="tool-shelf">
        <button :class="['tool-trigger', { open: showExplain }]" @click="toggleExplain">
          <span><b>看不懂代码?</b> · 逐行讲解、认符号、补概念</span>
          <span>{{ showExplain ? '收起 ↑' : '展开 ↓' }}</span>
        </button>
      </div>
      <div v-if="showExplain" class="panel explain-panel">
        <div class="explain-body">
          <button class="walk-trigger-inline" @click="openWalk">📖 逐行讲解（完整通读，从代码上滑出）</button>
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

      <div class="wr">
        <div class="thinking-head">
          <span class="thinking-kicker">这不是作业，写不出来也可以直接问知返</span>
          <div class="thinking-head-r">
            <span class="thinking-stage">现在 · {{ session.stage.slice(1) }}</span>
            <button class="thought-toggle" @click="thoughtOpen = !thoughtOpen">{{ thoughtOpen ? '收起 ▲' : '展开 ▼' }}</button>
          </div>
        </div>
        <h3 class="wr-title acp-serif">我的思考过程</h3>

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
          <div class="composer-box">
            <textarea
              v-model="draft" rows="1"
              placeholder="描述你的观察、猜测、验证…"
              @keydown.enter.exact.prevent="send"
            />
            <div class="composer-actions">
              <button class="send-btn" :disabled="sending" @click="send">发送</button>
            </div>
          </div>
        </div>
      </div>
    </div>
   </div>
  </div>
</template>

<style scoped>
.error { border-color: var(--red); color: var(--red); margin-bottom: 16px; }

/* ============ 做题页：浅色单焦点（设计稿 Arena B，1:1）============ */
.ws {
  position: fixed; inset: 0; z-index: 200; display: flex; padding: 24px; overflow: auto;
  background: radial-gradient(1100px 560px at 88% -12%, #efe6d6 0%, rgba(239,230,214,0) 58%), #f4f1ea;
}
.ws-card {
  flex: 1; min-height: 0; display: flex; flex-direction: column;
  background: #fcfbf7; border: 1px solid #e7e2d6; border-radius: 14px; overflow: hidden;
  box-shadow: 0 24px 60px -34px rgba(43,41,36,0.35);
}
.wt { flex: none; height: 60px; display: flex; align-items: center; gap: 26px; padding: 0 24px; background: #fcfbf7; border-bottom: 1px solid #ece5d8; }
.wt-brand { display: flex; align-items: center; gap: 10px; font-weight: 700; font-size: 16px; color: #2b2924; }
.wt-logo { width: 24px; height: 24px; border-radius: 7px; background: #c15f3c; color: #fff; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; }
.wt-nav { display: flex; gap: 22px; flex: 1; font-size: 14px; }
.wt-nav a { text-decoration: none; color: #8a8275; }
.wt-nav a:hover { color: #2b2924; }
.wt-nav a.wt-on, .wt-nav a.router-link-active { color: #2b2924; font-weight: 600; }
.wt-id { font-family: 'IBM Plex Mono', monospace; font-size: 12.5px; color: #8a8275; background: #f4efe5; border: 1px solid #e7e2d6; padding: 6px 13px; border-radius: 7px; }
.wt-quit { font-size: 13px; color: #6f695d; background: #fff; border: 1px solid #e7e2d6; padding: 7px 14px; border-radius: 8px; cursor: pointer; }
.wt-quit:hover { border-color: #c15f3c; color: #c15f3c; }
.wb { flex: 1; min-height: 0; display: flex; }
.wl { width: 60%; min-width: 0; border-right: 1px solid #ece5d8; display: flex; flex-direction: column; gap: 16px; padding: 20px; overflow-y: auto; background: #faf7f0; }
.wr { width: 40%; min-width: 0; display: flex; flex-direction: column; overflow: hidden; background: #fcfbf7; }

/* 代码卡（暖纸）*/
.cc { background: #fffdf8; border: 1px solid #ece4d4; border-radius: 11px; overflow: hidden; box-shadow: 0 1px 2px rgba(43,41,36,0.03); }
.cc-bar { height: 44px; display: flex; align-items: center; justify-content: space-between; padding: 0 16px; background: #f7f1e6; border-bottom: 1px solid #ece4d4; }
.cc-tab { font-family: 'IBM Plex Mono', monospace; font-size: 12.5px; color: #2b2924; background: #fffdf8; padding: 5px 12px; border-radius: 6px 6px 0 0; border-bottom: 2px solid #c15f3c; }
.cc-run { font-size: 13px; font-weight: 600; color: #fff; background: #c15f3c; border: none; border-radius: 7px; padding: 7px 16px; cursor: pointer; }
.cc-run:disabled { opacity: 0.55; cursor: not-allowed; }
.cc-edit { position: relative; display: flex; font-family: 'IBM Plex Mono', monospace; font-size: 13.5px; background: #fffdf8; min-height: 280px; max-height: 52vh; }
.cc-gutter { flex: none; width: 46px; text-align: right; padding: 16px 12px 16px 0; color: #c3b9a5; user-select: none; overflow: hidden; }
.cc-gutter div { height: 31px; line-height: 31px; cursor: pointer; }
.cc-gutter div:hover { color: #c15f3c; }
.cc-gutter div.on { color: #c15f3c; font-weight: 700; }
.cc-wrap { position: relative; flex: 1; min-width: 0; }
.cc-band { position: absolute; left: 0; right: 0; height: 31px; background: #f7e1d4; border-left: 3px solid #c15f3c; pointer-events: none; }
.cc-hl, .cc-ta { margin: 0; border: 0; padding: 16px; box-sizing: border-box; font-family: inherit; font-size: 13.5px; line-height: 31px; white-space: pre; tab-size: 4; }
.cc-hl { position: absolute; inset: 0; overflow: hidden; color: #5b5347; pointer-events: none; }
.cc-hl :deep(.t-kw) { color: #9a6a45; }
.cc-hl :deep(.t-bi) { color: #b07d3c; }
.cc-hl :deep(.t-num) { color: #b07d3c; }
.cc-hl :deep(.t-str) { color: #5c7a52; }
.cc-hl :deep(.t-com) { color: #a89e8c; font-style: italic; }
.cc-ta { position: absolute; inset: 0; width: 100%; height: 100%; resize: none; outline: none; background: transparent; color: transparent; caret-color: #c15f3c; overflow: auto; }
.cc-note { position: absolute; right: 16px; width: 320px; background: #fff; border: 1px solid #f0d8c8; border-left: 3px solid #c15f3c; border-radius: 10px; box-shadow: 0 18px 36px -16px rgba(193,95,60,0.35); padding: 12px 15px; z-index: 3; }
.cc-note-head { display: flex; align-items: center; gap: 8px; margin-bottom: 7px; }
.cc-note-line { font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; color: #fff; background: #c15f3c; padding: 2px 8px; border-radius: 5px; font-weight: 600; }
.cc-note-x { margin-left: auto; border: none; background: none; font-size: 16px; color: #a89e8c; cursor: pointer; line-height: 1; }
.cc-note-body { font-size: 13px; line-height: 1.7; color: #3a3530; }
.cc-term { border-top: 1px solid #1c2128; background: #11151b; }
.cc-term-bar { display: flex; align-items: center; gap: 10px; width: 100%; padding: 11px 16px; background: none; border: none; cursor: pointer; text-align: left; }
.cc-dots { display: inline-flex; gap: 6px; align-items: center; flex: none; }
.cc-dots i { width: 11px; height: 11px; border-radius: 50%; display: inline-block; }
.cc-dots i:nth-child(1) { background: #ff5f56; }
.cc-dots i:nth-child(2) { background: #ffbd2e; }
.cc-dots i:nth-child(3) { background: #27c93f; }
.cc-term-title { font-size: 12px; color: #8b94a0; flex: none; }
.cc-term-s { font-size: 13px; color: #c5cdd6; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cc-term-s.bad { color: #ff9d8c; }
.cc-term-c { font-size: 12px; color: #6b7480; }
.cc-term-body { padding: 4px 16px 12px; max-height: 160px; overflow: auto; }
.cc-term-body .console-out { color: #c5cdd6; font-size: 13px; margin: 0; white-space: pre-wrap; }
.cc-term-body .console-err { color: #ff9d8c; font-size: 13px; margin: 0; white-space: pre-wrap; }
.cc-term-body .console-muted { color: #6b7480; font-size: 12.5px; }

/* 看不懂代码 + explain（浅色）*/
.wl .tool-trigger { background: #fcfbf7; border: 1px solid #e7e2d6; border-radius: 11px; color: #6f695d; }
.wl .tool-trigger b { color: #2b2924; }
.wl .explain-panel { background: #fcfbf7; border: 1px solid #e7e2d6; border-radius: 11px; }
.wl .walk-trigger-inline { width: 100%; background: #f4efe5; border: 1px solid #e7e2d6; color: #6f695d; border-radius: 10px; padding: 10px; font-size: 13px; font-weight: 600; cursor: pointer; margin-bottom: 6px; }
.wl .walk-trigger-inline:hover { border-color: #c15f3c; color: #c15f3c; }

/* 右栏：我的思考过程（浅色，按设计）*/
.wr-title { font-family: var(--serif); font-size: 21px; font-weight: 600; color: #2b2924; margin: 0; padding: 4px 24px 0; }
.wr .thinking-head { padding: 18px 24px 0; border: none; align-items: flex-start; }
.wr .thinking-kicker { font-size: 12.5px; color: #8a8275; line-height: 1.5; }
.wr .thinking-head-r { display: flex; align-items: center; gap: 9px; flex: none; }
.wr .thinking-stage { background: #eaddd2; color: #a54e30; padding: 4px 11px; border-radius: 999px; font-size: 12px; font-weight: 600; }
.wr .thought-toggle { border: none; background: none; color: #a89e8c; font-size: 12.5px; cursor: pointer; }
.wr .thought-line { padding: 10px 24px 0; overflow-y: auto; }
.wr .chat { min-height: 0; flex: 1 1 auto; padding: 8px 24px; }
/* 返诗句：和正文一样的 24px 左右留白，别贴边 */
.wr .tutor-divider { padding: 16px 24px 12px; }
/* 输入框：按设计稿——卡片内 输入在上、发送在下右对齐（发送不再竖排） */
.wr .composer { display: block; padding: 12px 24px 18px; margin: 0; }
.wr .composer-box { background: #fff; border: 1px solid #e2dccd; border-radius: 12px; padding: 13px 15px; }
.wr .composer-box textarea {
  width: 100%; box-sizing: border-box; border: none; outline: none; resize: none; background: transparent;
  font-family: inherit; font-size: 13.5px; line-height: 1.5; color: var(--text);
}
.wr .composer-box textarea::placeholder { color: #b3ab9a; }
.wr .composer-actions { display: flex; justify-content: flex-end; margin-top: 12px; }
.wr .composer-actions .send-btn {
  background: #c15f3c; color: #fff; border: none; border-radius: 9px; padding: 8px 22px;
  font-size: 13px; font-weight: 700; cursor: pointer; white-space: nowrap;
}
.wr .composer-actions .send-btn:disabled { opacity: 0.55; cursor: not-allowed; }

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

/* 标题 + 接着做 文字按钮（稳定，不用图标库/SVG） */
.lobby-title { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.archive-btn {
  font-size: 13px; color: var(--muted); font-family: inherit; cursor: pointer;
  background: var(--panel); border: 1px solid var(--border); border-radius: 999px;
  padding: 4px 14px; transition: color 0.15s, border-color 0.15s, background 0.15s;
}
.archive-btn:hover { color: var(--primary); border-color: #dac9b8; background: var(--accent-soft); }
.lobby-sub { color: var(--muted); margin: 0; font-size: 15px; }

/* 灵犀感知层：一句安静的「读过你」，柔和不抢焦点（设计 11） */
.presence {
  margin: 0 0 18px; padding: 11px 15px;
  border-left: 3px solid #e0cdbb; border-radius: 0 8px 8px 0;
  background: rgba(193, 95, 60, 0.05);
  font-size: 14.5px; color: var(--text); line-height: 1.7;
}

/* 灵犀挫败台阶气泡：右下角飘出，几秒自退，不挡操作（设计 11） */
.lingxi-bubble {
  position: fixed; right: 24px; bottom: 24px; z-index: 60;
  display: flex; align-items: flex-start; gap: 9px; max-width: 320px;
  padding: 13px 16px; border-radius: 14px;
  background: rgba(252, 248, 241, 0.97); border: 1px solid #e6d6c4;
  box-shadow: 0 14px 38px -12px rgba(43, 41, 36, 0.4);
  font-size: 14px; line-height: 1.65; color: var(--text);
  backdrop-filter: blur(6px);
}
.lingxi-emoji { font-size: 17px; line-height: 1.4; flex-shrink: 0; }
.lingxi-text { flex: 1; }
.lingxi-fade-enter-active { transition: opacity 0.4s ease, transform 0.4s ease; }
.lingxi-fade-leave-active { transition: opacity 0.9s ease, transform 0.9s ease; }
.lingxi-fade-enter-from { opacity: 0; transform: translateY(12px); }
.lingxi-fade-leave-to { opacity: 0; transform: translateY(8px); }

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
/* 主角放大居中（大厅唯一焦点） */
.smart-open.hero { align-items: center; text-align: center; gap: 5px; padding: 26px 28px; margin-bottom: 14px; }
.smart-open.hero .smart-open-main { font-size: 21px; }

/* 安静入口：查看推荐与题库（跳能力画像） */
.browse-link {
  display: inline-block; text-decoration: none;
  font-size: 14px; color: var(--muted); padding: 4px 2px; transition: color 0.15s;
}
.browse-link:hover { color: var(--text); }

/* 档案面板：未完成关卡（接着做） */
.archive-overlay {
  position: fixed; inset: 0; z-index: 50; display: flex; align-items: center; justify-content: center;
  padding: 24px; background: rgba(43, 41, 36, 0.35);
}
.archive-panel {
  width: 100%; max-width: 480px; max-height: 80vh; overflow-y: auto;
  background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 24px;
  box-shadow: 0 24px 60px -28px rgba(43, 41, 36, 0.45);
}
.archive-head { display: flex; align-items: center; justify-content: space-between; }
.archive-head h3 { font-family: var(--serif); font-size: 18px; font-weight: 600; color: var(--text); margin: 0; }
.archive-close { border: none; background: none; font-size: 22px; line-height: 1; color: var(--muted); cursor: pointer; }
.archive-close:hover { color: var(--text); }
.archive-sub { font-size: 13px; color: var(--muted); margin: 6px 0 16px; }

/* 接着做：未完成关卡，最近一局置顶高亮 */
.resume { margin-bottom: 26px; }
.resume-title { font-family: var(--serif); font-size: 16px; font-weight: 600; color: var(--text); margin: 0 0 12px; }
.resume-card {
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  background: var(--panel); border: 1px solid var(--border); border-radius: 14px;
  padding: 16px 20px; margin-bottom: 12px;
}
.resume-card.featured { background: var(--accent-soft); border-color: #e0cdbb; }
.resume-card:last-child { margin-bottom: 0; }
.resume-info { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.resume-name { font-family: var(--serif); font-size: 16px; font-weight: 600; color: var(--text); }
.resume-stage { font-size: 13px; color: var(--primary); }
.resume-time { font-size: 12px; color: var(--muted); }
.resume-actions { display: flex; align-items: center; gap: 16px; flex-shrink: 0; }
.resume-go {
  border: none; background: none; font-family: var(--serif); font-size: 14.5px; font-weight: 600;
  color: var(--primary); cursor: pointer; transition: transform 0.18s;
}
.resume-go:hover { transform: translateX(4px); }
.resume-drop { border: none; background: none; font-size: 13px; color: var(--muted); cursor: pointer; }
.resume-drop:hover { color: var(--text); }
.resume-confirm { display: flex; flex-direction: column; gap: 10px; align-items: flex-end; flex-shrink: 0; max-width: 60%; }
.resume-confirm > span { font-size: 12.5px; color: var(--muted); text-align: right; line-height: 1.6; }
.resume-confirm-btns { display: flex; gap: 12px; }
.resume-drop-yes { border: none; background: none; font-size: 13.5px; color: var(--primary); cursor: pointer; }
.resume-keep { border: none; background: none; font-size: 13.5px; font-weight: 600; color: var(--text); cursor: pointer; }
.resume-more {
  border: none; background: none; cursor: pointer; padding: 8px 2px; margin-top: 4px;
  font-size: 13px; color: var(--muted);
}
.resume-more:hover { color: var(--text); }

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
.banner {
  margin-top: 14px; padding: 13px 16px; border-radius: 10px; font-size: 13.5px; line-height: 1.75;
  background: var(--accent-soft); color: #7a3f28;
  border-left: 3px solid var(--primary);
}
.banner b { font-weight: 600; }
.bf-title { font-weight: 600; color: var(--primary-dark); margin-bottom: 4px; }
.bf-body { font-size: 13px; line-height: 1.7; }
/* 提交修复=克制次按钮（运行才是该先点的、温暖主按钮），降低"被评判"压力 */
.submit-btn { color: var(--muted); }
.submit-btn:hover:not(:disabled) { color: var(--primary); border-color: var(--primary); }
/* 逐行讲解抽屉：从代码区底部上滑、覆盖代码下部，不撑高页面 */
.walk-drawer {
  position: absolute; left: 0; right: 0; bottom: 0; height: 60%;
  display: flex; flex-direction: column; z-index: 5;
  background: var(--panel); border-top: 2px solid var(--primary);
  box-shadow: 0 -8px 24px rgba(43,41,36,0.18); animation: walkUp 0.22s ease;
}
.walk-drawer.tall { height: 90%; }
@keyframes walkUp { from { transform: translateY(100%); } to { transform: translateY(0); } }
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
