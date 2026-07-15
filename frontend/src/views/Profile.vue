<script setup>
import { onMounted, ref, computed, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { api } from '../api'
import RadarChart from '../components/RadarChart.vue'
import GlossaryText from '../components/GlossaryText.vue'

const router = useRouter()
const route = useRoute()
function practiceVariant(pid) {
  router.push({ path: '/arena', query: { start: pid } })
}
// 从能力画像直接开题（IA：画像=推荐与选题中枢，doc 10）。复用 Arena 的 ?start= 自动开题，不改开题逻辑。
function start(pid) {
  router.push({ path: '/arena', query: { start: pid } })
}

// 推荐与题库（从大厅搬来，doc 10）。分类元数据与分组逻辑与 Arena 一致。
const recs = ref([])
const recsLoading = ref(false)
const patterns = ref([])
const openCats = reactive({})
function toggleCat(c) { openCats[c] = !openCats[c] }
const CATEGORY_META = {
  boundary: { label: '边界类', desc: '数组越界、差一错误——和「范围」打交道时最常见的坑。' },
  loop: { label: '循环类', desc: '循环次数、终止条件、累加逻辑里的细节失误。' },
  null: { label: '空值类', desc: '空对象、缺字段、None——没防住「什么都没有」的情况。' },
  arithmetic: { label: '算术类', desc: '除零、溢出等数值运算中的边界问题。' },
}
const CATEGORY_ORDER = ['boundary', 'loop', 'null', 'arithmetic']
const grouped = computed(() => {
  const byCat = {}
  for (const p of patterns.value) (byCat[p.category] ||= []).push(p)
  const order = [...CATEGORY_ORDER, ...Object.keys(byCat).filter((c) => !CATEGORY_ORDER.includes(c))]
  return order.filter((c) => byCat[c]?.length).map((c) => ({
    category: c, ...(CATEGORY_META[c] || { label: c, desc: '' }),
    items: byCat[c].sort((a, b) => (a.difficulty || '').localeCompare(b.difficulty || '')),
  }))
})

const ZH = {
  Log_Reading: '日志阅读', Boundary_Awareness: '边界意识', Root_Cause_Reasoning: '根因分析',
  Independent_Debug: '独立调试', Hypothesis_Testing: '假设验证', Internalization: '内化',
  AI_Review: 'AI代码审查', AI_Verification: 'AI回答验证', Prompt_Design: '提示词设计',
}
// 每项能力的大白话解释——让零基础学生看懂「这个分数代表我会了什么」
const CAP_DESC = {
  Log_Reading: '看懂报错信息，定位它指向哪一行',
  Boundary_Awareness: '想到空值、边界、极端输入这些容易翻车的情况',
  Root_Cause_Reasoning: '说清楚 Bug「为什么」会发生，而不只是改对',
  Independent_Debug: '少依赖提示，自己把问题修好',
  Hypothesis_Testing: '主动构造输入去验证猜测',
  Internalization: '能复述成因、举一反三，真正学会',
  AI_Review: '让 AI 帮你审代码并判断它说得对不对',
  AI_Verification: '不盲信 AI，会动手核对它的回答',
  Prompt_Design: '把问题问清楚，让 AI 更好地帮你',
}

const profile = ref(null)
const patternNames = ref({})  // pattern_id -> 中文名，用来替换开发编号
const error = ref('')
const expanded = ref(null) // capability name
const events = ref([])
const loadingEvents = ref(false)

onMounted(load)

async function load() {
  try {
    profile.value = await api.getProfile()
    const ps = await api.listPatterns().catch(() => [])
    patterns.value = ps
    patternNames.value = Object.fromEntries(ps.map((p) => [p.id, p.name]))
    if (grouped.value[0]) openCats[grouped.value[0].category] = true  // 默认只展开第一组
  } catch (e) {
    error.value = '加载失败：' + e.message
  }
  loadRecs()
}

async function loadRecs() {
  recsLoading.value = true
  try { recs.value = await api.getRecommendations() }
  catch (e) { recs.value = [] }
  finally { recsLoading.value = false }
}

// 关卡进度概览：各状态计数
const progress = computed(() => {
  const ks = profile.value?.knowledge_states || []
  const c = { 已内化: 0, 已解决: 0, 已接触: 0 }
  for (const s of ks) if (s.state in c) c[s.state]++
  return { ...c, total: ks.length }
})

async function drill(cap) {
  if (expanded.value === cap) {
    expanded.value = null
    return
  }
  expanded.value = cap
  loadingEvents.value = true
  try {
    events.value = await api.getCapabilityEvents(cap)
  } catch (e) {
    events.value = []
  } finally {
    loadingEvents.value = false
  }
}

function fmtTime(ts) {
  return ts ? ts.slice(0, 19).replace('T', ' ') : ''
}

// B0 知识点掌握度：档位 → 4 格进度
const MASTERY_LEVEL = { 生疏: 1, 在学: 2, 掌握: 3, 熟练: 4 }
// 把 confidence 换成大白话「练习多少」，避免「已掌握+稳定度低」的认知矛盾
const PRACTICE_LABEL = { 高: '练习充分', 中: '练习适中', 低: '练习还少' }
const mastery = computed(() => profile.value?.knowledge_mastery || [])
const nextPractice = computed(() => profile.value?.practice?.next || null)
function practiceKp(kp) {
  const p = profile.value?.practice?.by_kp?.[kp]
  if (p) router.push({ path: '/arena', query: { start: p.pattern_id } })
}

// 知识点 → 含该 kp 的题及其状态（把原「知识点状态」表的信息折进翻转卡背面）
const kpPatterns = computed(() => {
  const map = {}
  for (const s of profile.value?.knowledge_states || []) {
    for (const kp of (s.knowledge_points || [])) {
      (map[kp] ||= []).push({ name: patternNames.value[s.pattern_id] || s.pattern_id,
                              state: s.state, variant: s.variant || null })
    }
  }
  return map
})
// 该知识点下可做的变式题（来自某道已内化题的 variant），保留原"做变式巩固"入口
function kpVariant(kp) {
  return (kpPatterns.value[kp] || []).map((p) => p.variant).find(Boolean) || null
}
// 展开态（点击切换，往下顶、自动撑高，不裁字不滚动）
const expandedKps = ref(new Set())
function toggleExpand(kp) {
  const s = expandedKps.value
  s.has(kp) ? s.delete(kp) : s.add(kp)
}
// 按「该不该练」排序：建议再练的排前，已掌握/熟练垫后 —— 一眼看到该补哪
const sortedMastery = computed(() =>
  [...mastery.value].sort((a, b) => {
    if (a.weak !== b.weak) return a.weak ? -1 : 1
    return (MASTERY_LEVEL[a.mastery] || 0) - (MASTERY_LEVEL[b.mastery] || 0)
  }))

// 下半部分用标签页：一次只看一块，避免页面又长又吵
const tab = ref(route.query.tab === '推荐' ? '推荐' : '能力')   // 默认能力雷达（设计稿：雷达是主角）；'能力' | '知识点' | '推荐'

// 维度还没数据时，解释它测什么、怎么才会有分（避免空维度看起来像坏了）
const DIM_HINT = {
  'AI协作能力': '衡量你「会不会用 AI」：审查 AI 给的代码、核对 AI 的说法对不对、把问题问清楚。在你和导师对话中主动质疑、验证它的说法时才会记录——目前还没有这类记录。',
  'Debug能力': '衡量你自己排错的本事：读报错、想边界、找根因、独立调试。完成闯关就会累计。',
}
const unevaluatedDims = computed(() =>
  (profile.value?.dimensions || []).filter((d) => d.score == null))

// 雷达画 6 个 Debug 能力（设计稿：日志阅读/边界意识/根因分析/独立调试/假设验证/内化），而非 2 个高层维度
const RADAR_CAPS = ['Log_Reading', 'Boundary_Awareness', 'Root_Cause_Reasoning', 'Independent_Debug', 'Hypothesis_Testing', 'Internalization']
const radarDims = computed(() => RADAR_CAPS.map((cap) => {
  const v = profile.value?.vector?.[cap]
  return { name: ZH[cap] || cap, score: v && v.score != null ? Math.round(v.score) : null, confidence: v?.confidence }
}))

// 覆盖度（治 #18 虚高）：给维度分一个语境——「这一维你练了几项里的几项」。
// 单个子能力就能把维度分顶高，所以必须把覆盖度亮出来，分数才诚实。
const coverage = computed(() => (profile.value?.dimensions || []).filter((d) => d.total))
</script>

<template>
  <div v-if="error" class="panel error">{{ error }}</div>
  <div v-else-if="!profile" class="panel">加载中…</div>
  <div v-else class="layout">
    <header class="profile-head">
      <div>
        <span>证据归拢</span>
        <h1>能力画像</h1>
        <p>这里的每个判断都来自真实练习过程，不是 AI 凭印象给出的标签。</p>
      </div>
      <RouterLink to="/timeline">回到我的成长 →</RouterLink>
    </header>
    <!-- 进度概览：横跨整页，一眼看懂学到哪了 -->
    <div class="overview">
      <div class="ov-item">
        <span class="ov-num done">{{ progress.已内化 }}</span>
        <span class="ov-label">已内化</span>
        <span class="ov-sub">真正学会</span>
      </div>
      <div class="ov-item">
        <span class="ov-num solved">{{ progress.已解决 }}</span>
        <span class="ov-label">已解决</span>
        <span class="ov-sub">修复过，待内化</span>
      </div>
      <div class="ov-item">
        <span class="ov-num seen">{{ progress.已接触 }}</span>
        <span class="ov-label">学习中</span>
        <span class="ov-sub">已开始挑战</span>
      </div>
      <div class="ov-item ov-empty">
        <p v-if="!progress.total" class="note">还没有挑战记录——去训练场开第一关吧。</p>
        <p v-else class="note">共挑战 {{ progress.total }} 个 Bug 模式。每内化一个，知识点就真正属于你。</p>
      </div>
    </div>

    <!-- 标签页：一次只看一块，页面不再又长又吵 -->
    <div class="tabbar">
      <button :class="['tab', { on: tab === '能力' }]" @click="tab = '能力'">能力雷达</button>
      <button :class="['tab', { on: tab === '知识点' }]" @click="tab = '知识点'">知识点</button>
      <button :class="['tab', { on: tab === '推荐' }]" @click="tab = '推荐'">推荐与题库</button>
    </div>

    <!-- 能力雷达 + 能力明细（同一标签，左右并排） -->
    <div v-show="tab === '能力'" class="tab-pane cap-pane">
      <div class="panel radar-panel">
        <h3>能力雷达</h3>
        <RadarChart :dimensions="radarDims" />
        <div v-if="coverage.length" class="coverage">
          <span v-for="d in coverage" :key="d.name" class="cov-item">{{ d.name }} · 练了 <b>{{ d.trained }}/{{ d.total }}</b> 项</span>
        </div>
        <p v-if="coverage.length" class="cov-note">分数按整个维度算——还没练的子能力算 0，练得越全面分数越高。</p>
        <div class="legend"><span class="dot low" /> 灰色=数据还少（事件&lt;5），多练会更准</div>
        <details v-for="d in unevaluatedDims" :key="d.name" class="dim-hint">
          <summary><b>「{{ d.name }}」还未评估</b></summary>
          {{ DIM_HINT[d.name] || '多练几关就会有数据。' }}
        </details>
      </div>
      <div class="panel">
        <h3>能力明细 <small class="h3-sub">点条目看证据</small></h3>
        <div v-if="!Object.keys(profile.vector).length" class="note">还没有能力数据——完成第一关后回来看看。</div>
        <div v-for="(v, cap) in profile.vector" :key="cap" class="cap-row">
          <button class="cap-head" @click="drill(cap)" :title="CAP_DESC[cap] || ''">
            <span class="cap-name">{{ ZH[cap] || cap }}</span>
            <span class="bar"><span class="fill" :style="{ width: v.score + '%' }" /></span>
            <span class="cap-score" :class="{ low: v.confidence === 'low' }">
              {{ v.score }}<small>（{{ v.events_count }}）</small>
            </span>
          </button>
          <div v-if="expanded === cap" class="events">
            <div v-if="loadingEvents" class="note">加载中…</div>
            <div v-for="e in events" :key="e.event_id" class="event">
              <span :class="['delta', e.delta > 0 ? 'pos' : 'neg']">{{ e.delta > 0 ? '+' : '' }}{{ e.delta }}</span>
              <div class="event-body">
                <div class="evidence">{{ e.evidence.summary }}</div>
                <div class="meta">{{ e.producer === 'rule' ? '规则判定' : 'AI判定' }} · {{ fmtTime(e.timestamp) }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 知识点展开卡 -->
    <div v-show="tab === '知识点'" class="tab-pane">
      <div class="panel" v-if="mastery.length">
        <div class="km-head">
          <h3>知识点 <small class="h3-sub">点卡片展开看详情</small></h3>
          <div v-if="nextPractice" class="km-next">
            <span class="km-next-label">下一题推荐</span>
            <span class="km-next-kp">{{ nextPractice.kp }}</span>
            <button class="km-next-btn" @click="practiceKp(nextPractice.kp)">去练 →</button>
          </div>
        </div>
        <div class="kpc-grid">
          <div v-for="m in sortedMastery" :key="m.kp"
               :class="['kpc', { open: expandedKps.has(m.kp) }]" @click="toggleExpand(m.kp)">
            <!-- 收起：名字 + 掌握度 + 一句话状态 -->
            <div class="kpc-head">
              <div class="kpc-name"><GlossaryText :text="m.kp" /></div>
              <div class="kpc-dots" :title="m.mastery">
                <i v-for="n in 4" :key="n" :class="['kpc-dot', { on: n <= MASTERY_LEVEL[m.mastery] }]" />
              </div>
            </div>
            <div class="kpc-status">
              <span class="kpc-mastery" :class="m.mastery">{{ m.mastery }}</span>
              <span v-if="m.weak" class="kpc-flag">· 建议再练</span>
              <span class="kpc-caret">{{ expandedKps.has(m.kp) ? '▴' : '▾' }}</span>
            </div>
            <!-- 展开：练习 + 建议 + 相关题 + 去练（向下撑高，不裁不滚） -->
            <div class="kpc-detail">
              <div class="kpc-detail-inner">
                <div class="kpc-back-line">练习：{{ PRACTICE_LABEL[m.confidence] }}</div>
                <div v-if="m.weak" class="kpc-back-line reason">建议：{{ m.weak_reason }}</div>
                <div v-if="kpPatterns[m.kp]?.length" class="kpc-pats">
                  <div v-for="(p, i) in kpPatterns[m.kp]" :key="i" class="kpc-pat">
                    <span class="kpc-pat-name">{{ p.name }}</span><span :class="['state', p.state]">{{ p.state }}</span>
                  </div>
                </div>
                <button v-if="profile.practice.by_kp[m.kp]" class="kpc-go"
                        @click.stop="practiceKp(m.kp)">去练 →</button>
                <button v-else-if="kpVariant(m.kp)" class="kpc-go"
                        @click.stop="practiceVariant(kpVariant(m.kp).id)">做变式巩固 →</button>
              </div>
            </div>
          </div>
        </div>
        <p class="note km-foot">「已解决」= AI 帮助下修复过；「已内化」= 复述判定通过（说清<GlossaryText text="根因" />/定位/<GlossaryText text="迁移" />）。</p>
      </div>
    </div>

    <!-- 推荐与题库：从大厅搬来（doc 10）。能力画像=选题中枢：看完状态，从这儿挑下一题。 -->
    <div v-show="tab === '推荐'" class="tab-pane sel-pane">
      <div class="panel">
        <h3>智能推荐 <small class="h3-sub">按你的画像挑，点开始挑战</small></h3>
        <p v-if="recsLoading" class="note">正在根据你的能力画像生成推荐…</p>
        <p v-else-if="!recs.length" class="note">暂时没有可推荐的——可能已把现有题都内化了，去下面浏览全部复习。</p>
        <div v-else class="sel-recs">
          <button v-for="r in recs" :key="r.id" class="sel-rec" @click="start(r.id)">
            <span class="sel-rec-reason">{{ r.reason }}</span>
            <span class="sel-rec-name">{{ r.name }}</span>
            <span class="sel-rec-meta">{{ r.difficulty }}<template v-if="(r.knowledge_points || []).length"> · {{ r.knowledge_points.join('、') }}</template></span>
          </button>
        </div>
      </div>
      <div class="panel">
        <h3>浏览全部题目 <small class="h3-sub">{{ patterns.length }} 道，按类型分组</small></h3>
        <div v-for="g in grouped" :key="g.category" class="sel-cat">
          <button class="sel-cat-head" @click="toggleCat(g.category)">
            <span class="sel-caret" :class="{ open: openCats[g.category] }">▸</span>
            <span class="sel-cat-title">{{ g.label }}</span>
            <span class="sel-cat-count">{{ g.items.length }} 题</span>
            <span class="sel-cat-desc">{{ g.desc }}</span>
          </button>
          <div v-show="openCats[g.category]" class="sel-items">
            <button v-for="p in g.items" :key="p.id" class="sel-item" @click="start(p.id)">
              <span class="sel-item-name">{{ p.name }}</span>
              <span class="sel-item-diff">{{ p.difficulty }}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.error { border-color: var(--red); color: var(--red); }
.layout { display: flex; flex-direction: column; gap: 16px; }
.profile-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; padding: 5px 2px 2px; }
.profile-head span { color: var(--primary); font-size: 11px; font-weight: 700; letter-spacing: .1em; }
.profile-head h1 { margin: 5px 0 5px; font-size: 26px; }
.profile-head p { margin: 0; color: var(--muted); font-size: 13px; line-height: 1.65; }
.profile-head a { color: var(--muted); font-size: 13px; text-decoration: none; padding-top: 8px; white-space: nowrap; }
.profile-head a:hover { color: var(--primary); }
h3 { margin-top: 0; font-size: 17px; }
.h3-sub { font-size: 12px; font-weight: 400; color: var(--muted); }
.note { color: var(--muted); font-size: 13px; line-height: 1.6; }

/* 标签栏 */
.tabbar { display: inline-flex; gap: 4px; padding: 4px; background: #ece6da; border-radius: 11px; align-self: flex-start; }
.tab { border: none; background: transparent; color: var(--muted); font-size: 14px;
  padding: 7px 18px; border-radius: 8px; font-family: var(--serif); cursor: pointer; }
.tab:hover:not(.on) { color: var(--text); }
.tab.on { background: var(--panel); color: var(--primary); box-shadow: 0 1px 3px rgba(43,41,36,0.08); }
.tab-pane { }
.cap-pane { display: grid; grid-template-columns: 360px 1fr; gap: 16px; align-items: start; }
@media (max-width: 760px) { .cap-pane { grid-template-columns: 1fr; } }
@media (max-width: 640px) { .profile-head { flex-direction: column; gap: 4px; } }
.dim-hint summary { cursor: pointer; }

/* 进度概览（横跨两列） */
.overview {
  grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 14px; align-items: stretch;
  background: var(--panel); border: 1px solid var(--border); border-radius: 14px;
  padding: 18px 22px; box-shadow: 0 1px 2px rgba(43,41,36,0.03);
}
.ov-item { display: flex; flex-direction: column; gap: 2px; padding-right: 26px; }
.ov-item:not(.ov-empty) { border-right: 1px solid var(--border); }
.ov-num { font-family: var(--serif); font-size: 30px; font-weight: 600; line-height: 1.1; }
.ov-num.done { color: var(--green); }
.ov-num.solved { color: var(--primary); }
.ov-num.seen { color: var(--muted); }
.ov-label { font-size: 14px; font-weight: 600; }
.ov-sub { font-size: 12px; color: var(--muted); }
.ov-empty { border-right: none; flex: 1; justify-content: center; min-width: 200px; padding-right: 0; }

/* 知识点翻转卡 */
.km-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.km-next { display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap;
  background: var(--accent-soft); border-radius: 8px; padding: 5px 10px; }
.km-next-label { font-size: 12px; color: var(--primary-dark); font-weight: 600; }
.km-next-kp { font-size: 13px; font-weight: 600; }
.km-next-btn {
  font-size: 12.5px; color: var(--primary); background: var(--panel);
  border: 1px solid var(--border); border-radius: 7px; padding: 2px 10px; white-space: nowrap;
}
.km-next-btn:hover { border-color: var(--primary); }
.km-foot { margin-top: 12px; }

.kpc-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; margin-top: 12px; align-items: start; }
.kpc {
  border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; background: var(--panel);
  cursor: pointer; box-shadow: 0 1px 2px rgba(43,41,36,0.04); transition: border-color 0.15s, box-shadow 0.15s;
}
.kpc:hover { border-color: var(--primary); }
.kpc.open { border-color: var(--primary); box-shadow: 0 2px 8px rgba(43,41,36,0.07); }
.kpc-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.kpc-name { font-family: var(--serif); font-size: 15px; font-weight: 600; line-height: 1.3;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.kpc-dots { display: inline-flex; gap: 4px; padding-top: 5px; flex-shrink: 0; }
.kpc-dot { width: 8px; height: 8px; border-radius: 50%; background: #e7e2d6; display: inline-block; }
.kpc-dot.on { background: var(--primary); }
.kpc-status { display: flex; align-items: center; gap: 4px; margin-top: 7px; font-size: 13px; }
.kpc-mastery.生疏 { color: var(--muted); }
.kpc-mastery.在学 { color: var(--primary-dark); }
.kpc-mastery.掌握 { color: var(--primary); }
.kpc-mastery.熟练 { color: var(--green); font-weight: 600; }
.kpc-flag { font-size: 12px; color: #7a3f28; }
.kpc-caret { margin-left: auto; font-size: 11px; color: var(--muted); }

/* 展开详情：grid-rows 0fr→1fr 平滑撑高，自动高度，不裁不滚 */
.kpc-detail { display: grid; grid-template-rows: 0fr; transition: grid-template-rows 0.28s ease; }
.kpc.open .kpc-detail { grid-template-rows: 1fr; }
.kpc-detail-inner { overflow: hidden; display: flex; flex-direction: column; gap: 5px; }
.kpc.open .kpc-detail-inner { margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--border); }
.kpc-back-line { font-size: 12.5px; color: var(--text); }
.kpc-back-line.reason { color: #7a3f28; line-height: 1.4; }
.kpc-pats { display: flex; flex-direction: column; gap: 4px; margin: 2px 0; min-width: 0; }
.kpc-pat { font-size: 11.5px; color: var(--muted); display: flex; align-items: center; gap: 6px; justify-content: space-between; }
.kpc-pat-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kpc-go {
  align-self: flex-start; margin-top: 3px; font-size: 12.5px; color: var(--primary);
  background: var(--accent-soft); border: 1px solid var(--border); border-radius: 7px; padding: 3px 11px;
}
.kpc-go:hover { border-color: var(--primary); }

/* 推荐与题库（选题中枢，doc 10） */
.sel-pane { display: flex; flex-direction: column; gap: 16px; }
.sel-recs { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; margin-top: 10px; }
.sel-rec {
  display: flex; flex-direction: column; gap: 5px; text-align: left; cursor: pointer;
  background: var(--accent-soft); border: 1px solid #e0cdbb; border-radius: 12px; padding: 13px 15px;
  transition: transform 0.18s, box-shadow 0.18s;
}
.sel-rec:hover { transform: translateY(-2px); color: inherit; box-shadow: 0 12px 26px -18px rgba(193,95,60,0.4); }
.sel-rec-reason { font-size: 12.5px; font-weight: 600; color: var(--primary); }
.sel-rec-name { font-family: var(--serif); font-size: 15px; font-weight: 600; color: var(--text); }
.sel-rec-meta { font-size: 12px; color: var(--muted); }
.sel-cat { border-bottom: 1px solid var(--border); }
.sel-cat:last-child { border-bottom: none; }
.sel-cat-head {
  display: flex; align-items: baseline; gap: 8px; width: 100%; text-align: left;
  background: none; border: none; padding: 11px 2px; cursor: pointer; flex-wrap: wrap;
}
.sel-caret { color: var(--muted); font-size: 12px; transition: transform 0.18s; align-self: center; }
.sel-caret.open { transform: rotate(90deg); }
.sel-cat-title { font-family: var(--serif); font-size: 15px; font-weight: 600; color: var(--text); }
.sel-cat-count { font-size: 12px; color: var(--muted); }
.sel-cat-desc { font-size: 12px; color: var(--muted); flex: 1; min-width: 160px; }
.sel-items { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; padding: 4px 0 12px; }
.sel-item {
  display: flex; align-items: center; justify-content: space-between; gap: 8px; text-align: left; cursor: pointer;
  background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 11px 13px; transition: border-color 0.15s;
}
.sel-item:hover { border-color: var(--primary); color: inherit; }
.sel-item-name { font-size: 13.5px; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sel-item-diff { font-size: 11.5px; color: var(--muted); flex-shrink: 0; }

.radar-panel { display: flex; flex-direction: column; align-items: center; }
.radar-panel h3 { align-self: flex-start; }
.legend { font-size: 12px; color: var(--muted); margin-top: 8px; }
.coverage { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 12px; }
.cov-item { font-size: 12.5px; color: var(--muted); }
.cov-item b { color: var(--primary); font-weight: 600; }
.cov-note { font-size: 12px; color: var(--muted); line-height: 1.6; margin: 8px 0 0; }
.dim-hint {
  font-size: 12.5px; color: var(--muted); line-height: 1.65; margin-top: 10px;
  background: var(--bg); border-radius: 8px; padding: 9px 11px;
}
.dim-hint b { color: var(--text); font-weight: 600; }
.dot.low { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }

.right-col { display: flex; flex-direction: column; gap: 18px; }
.empty-cap { padding: 6px 2px; }
.empty-cap p { margin: 0 0 6px; }
.cap-row { border-bottom: 1px solid var(--border); }
.cap-row:last-child { border-bottom: none; }
.cap-head {
  display: grid; grid-template-columns: 1fr 120px 64px; gap: 14px; align-items: center;
  width: 100%; border: none; background: none; padding: 12px 4px; text-align: left;
  border-radius: 8px; transition: background 0.15s;
}
.cap-head:hover { background: var(--accent-soft); }
.cap-info { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.cap-name { font-weight: 600; font-size: 14.5px; }
.cap-desc { font-size: 12px; color: var(--muted); line-height: 1.45; }
.bar { height: 8px; background: #ece6da; border-radius: 999px; overflow: hidden; }
.fill { display: block; height: 100%; background: var(--primary); border-radius: 999px; transition: width 0.4s ease; }
.cap-score { font-weight: 700; color: var(--primary); text-align: right; font-size: 15px; }
.cap-score.low { color: var(--muted); }
.cap-score small { font-weight: 400; color: var(--muted); font-size: 11px; }

.events { padding: 4px 4px 14px 14px; display: flex; flex-direction: column; gap: 9px; }
.event { display: flex; gap: 10px; align-items: flex-start; }
.delta {
  font-weight: 700; font-size: 13px; min-width: 30px; text-align: center;
  border-radius: 6px; padding: 2px 4px;
}
.delta.pos { background: #e4ede0; color: var(--green); }
.delta.neg { background: #f6e0da; color: var(--red); }
.evidence { font-size: 13px; line-height: 1.5; }
.meta { font-size: 12px; color: var(--muted); }

.ks-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.ks-table th, .ks-table td { text-align: left; padding: 9px 6px; border-bottom: 1px solid var(--border); vertical-align: top; }
.ks-table th { color: var(--muted); font-weight: 600; font-size: 13px; }
.ks-table tr:last-child td { border-bottom: none; }
.kp-pill {
  display: inline-block; font-size: 12px; padding: 1px 8px; margin: 0 4px 4px 0;
  border-radius: 6px; background: var(--accent-soft); color: var(--primary-dark);
}
.state { font-size: 12px; padding: 3px 11px; border-radius: 999px; background: #f1f3f5; white-space: nowrap; }
.state.已接触 { background: #f3ecd6; color: #87651f; }
.state.已解决 { background: var(--accent-soft); color: var(--primary-dark); }
.state.已内化 { background: #e4ede0; color: #3f5837; }
.variant-link {
  font-size: 12.5px; padding: 4px 10px; border-radius: 7px; white-space: nowrap;
  border: 1px solid var(--border); background: var(--accent-soft); color: var(--primary-dark);
}
.variant-link:hover { border-color: var(--primary); color: var(--primary); }
</style>
