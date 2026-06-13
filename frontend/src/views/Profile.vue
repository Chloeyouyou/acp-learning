<script setup>
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import RadarChart from '../components/RadarChart.vue'
import GlossaryText from '../components/GlossaryText.vue'

const router = useRouter()
function practiceVariant(pid) {
  router.push({ path: '/arena', query: { start: pid } })
}

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
    patternNames.value = Object.fromEntries(ps.map((p) => [p.id, p.name]))
  } catch (e) {
    error.value = '加载失败：' + e.message
  }
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

// 维度还没数据时，解释它测什么、怎么才会有分（避免空维度看起来像坏了）
const DIM_HINT = {
  'AI协作能力': '衡量你「会不会用 AI」：审查 AI 给的代码、核对 AI 的说法对不对、把问题问清楚。在你和导师对话中主动质疑、验证它的说法时才会记录——目前还没有这类记录。',
  'Debug能力': '衡量你自己排错的本事：读报错、想边界、找根因、独立调试。完成闯关就会累计。',
}
const unevaluatedDims = computed(() =>
  (profile.value?.dimensions || []).filter((d) => d.score == null))
</script>

<template>
  <div v-if="error" class="panel error">{{ error }}</div>
  <div v-else-if="!profile" class="panel">加载中…</div>
  <div v-else class="layout">
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

    <div class="panel radar-panel">
      <h3>能力雷达</h3>
      <p class="note">每项能力都由你的真实表现累计而来，点下方能力条可看到具体证据。</p>
      <RadarChart :dimensions="profile.dimensions" />
      <div class="legend">
        <span class="dot low" /> 灰色 = 数据还少（事件少于 5 个），多练几关会更准
      </div>
      <div v-for="d in unevaluatedDims" :key="d.name" class="dim-hint">
        <b>「{{ d.name }}」还未评估</b>{{ DIM_HINT[d.name] ? '——' + DIM_HINT[d.name] : '，多练几关就会有数据。' }}
      </div>
    </div>

    <div class="right-col">
      <div class="panel">
        <h3>能力明细</h3>
        <div v-if="!Object.keys(profile.vector).length" class="empty-cap">
          <p>还没有能力数据。</p>
          <p class="note">能力分不是考出来的，而是你在闯关时一点点「攒」出来的——完成第一关后回来看看。</p>
        </div>
        <div v-for="(v, cap) in profile.vector" :key="cap" class="cap-row">
          <button class="cap-head" @click="drill(cap)">
            <span class="cap-info">
              <span class="cap-name">{{ ZH[cap] || cap }}</span>
              <span class="cap-desc"><GlossaryText :text="CAP_DESC[cap] || ''" /></span>
            </span>
            <span class="bar"><span class="fill" :style="{ width: v.score + '%' }" /></span>
            <span class="cap-score" :class="{ low: v.confidence === 'low' }">
              {{ v.score }}<small>（{{ v.events_count }}）</small>
            </span>
          </button>
          <div v-if="expanded === cap" class="events">
            <div v-if="loadingEvents" class="note">加载中…</div>
            <div v-for="e in events" :key="e.event_id" class="event">
              <span :class="['delta', e.delta > 0 ? 'pos' : 'neg']">
                {{ e.delta > 0 ? '+' : '' }}{{ e.delta }}
              </span>
              <div class="event-body">
                <div class="evidence">{{ e.evidence.summary }}</div>
                <div class="meta">
                  {{ e.producer === 'rule' ? '规则判定' : 'AI判定' }}
                  · 置信度 {{ e.confidence }} · {{ fmtTime(e.timestamp) }}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="panel">
        <h3>知识点状态</h3>
        <div v-if="!profile.knowledge_states.length" class="note">还没有挑战记录。</div>
        <table v-else class="ks-table">
          <thead>
            <tr><th>挑战过的题</th><th>涉及知识点</th><th>状态</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="s in profile.knowledge_states" :key="s.pattern_id">
              <td>{{ patternNames[s.pattern_id] || s.pattern_id }}</td>
              <td>
                <span v-for="kp in s.knowledge_points" :key="kp" class="kp-pill">
                  <GlossaryText :text="kp" />
                </span>
              </td>
              <td><span :class="['state', s.state]">{{ s.state }}</span></td>
              <td>
                <button v-if="s.variant" class="variant-link"
                        :title="'做变式：' + s.variant.name"
                        @click="practiceVariant(s.variant.id)">做变式巩固 →</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p class="note">「已解决」= 在 AI 帮助下修复过；「已内化」= 通过复述判定（说清<GlossaryText text="根因" /> / 定位 / <GlossaryText text="迁移" />，达标 ≥2 项）。</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.error { border-color: var(--red); color: var(--red); }
.layout { display: grid; grid-template-columns: 360px 1fr; gap: 18px; align-items: start; }
h3 { margin-top: 0; font-size: 17px; }
.note { color: var(--muted); font-size: 13px; line-height: 1.6; }

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

.radar-panel { display: flex; flex-direction: column; align-items: center; }
.radar-panel h3 { align-self: flex-start; }
.legend { font-size: 12px; color: var(--muted); margin-top: 8px; }
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
