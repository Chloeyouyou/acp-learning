<script setup>
import { onMounted, reactive, ref, computed, nextTick } from 'vue'
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
const showPrimer = ref(true)         // 练前小灶是否展开
const showSyntax = ref(false)        // 「代码怎么读」符号扫盲是否展开（默认收起，需要的人点开）

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
    showPrimer.value = true   // 新关卡默认展开练前小灶
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

async function submit() {
  if (submitting.value) return
  submitting.value = true
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
        💡 <b>练前小灶</b> · 这道题会用到这些概念，看不懂代码先花一分钟补一补
      </button>
      <div v-show="showPrimer" class="primer-body">
        <!-- 代码符号扫盲：完全没见过代码的人先认认这些符号 -->
        <div v-if="syntaxBricks.length" class="syntax-box">
          <button class="syntax-head" @click="showSyntax = !showSyntax">
            <span class="primer-caret" :class="{ open: showSyntax }">▸</span>
            🔤 完全没接触过代码？先认认这道题里的符号（{{ syntaxBricks.length }} 个）
          </button>
          <div v-show="showSyntax" class="syntax-list">
            <div v-for="b in syntaxBricks" :key="b.name" class="syntax-item">
              <span class="syntax-name">{{ b.name }}</span>
              <span class="syntax-desc">{{ b.desc }}</span>
            </div>
          </div>
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
          <button class="primary" :disabled="submitting || session.fixed" @click="submit">
            {{ submitting ? '判定中…' : '提交修复' }}
          </button>
        </div>
        <textarea v-model="session.code" class="code" spellcheck="false" :disabled="session.fixed" />
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
          ✅ <b>修复通过测试</b>，知识点现在是「已解决」。别急着结束——继续和导师完成 ⑤验证（边界测试）与
          ⑥内化（复述成因、定位、迁移），才能升级为「已内化」。
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
.syntax-name {
  font-family: Consolas, monospace; font-size: 13px; font-weight: 700; color: var(--primary-dark);
}
.syntax-desc { font-size: 13px; color: var(--muted); line-height: 1.6; }

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
