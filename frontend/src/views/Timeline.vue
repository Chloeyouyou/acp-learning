<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import GlossaryText from '../components/GlossaryText.vue'

const router = useRouter()
const data = ref(null)
const error = ref('')
const reviewDue = ref([])

onMounted(async () => {
  try {
    data.value = await api.getTimeline()
  } catch (e) {
    error.value = '加载失败：' + e.message
  }
  try {
    const r = await api.getReviewQueue()
    reviewDue.value = r.due || []
  } catch (e) { /* 复习卡拿不到不阻塞主时间线 */ }
})

const _CAT = { boundary: '边界条件', loop: '循环逻辑', null: '空值/None', arithmetic: '算术运算' }
function catLabel(c) { return _CAT[c] || c }

function startReview(pid) {
  router.push({ path: '/arena', query: { start: pid, mode: 'review' } })
}

// 报错类型 → 大白话（治"看不懂英文报错"）
const ERR = {
  IndexError: '下标越界', TypeError: '类型错误', KeyError: '键不存在',
  NameError: '名字未定义', ValueError: '取值不合法', AttributeError: '属性不存在',
  ZeroDivisionError: '除以了零', RecursionError: '递归太深', Timeout: '卡死超时',
  WrongAnswer: '输出不对', RuntimeError: '运行出错',
}
const KIND = { RE: '运行报错', WA: '输出不对', HANG: '卡死超时', OK: '✓ 通过' }

function attemptLabel(a) {
  if (a.kind === 'OK') return '✓ 通过'
  return ERR[a.error_family] || a.error_family || KIND[a.kind] || a.kind
}

// 一个回合内：把连续相同的结果合并，突出"演变"（下标越界→输出不对→通过）
function chain(attempts) {
  const out = []
  for (const a of attempts) {
    const label = attemptLabel(a)
    const ok = a.kind === 'OK'
    if (out.length && out[out.length - 1].label === label) continue
    out.push({ label, ok })
  }
  return out
}

// 按天分行的回合视图：每行带标签（多天→日期，单次→"尝试链"），
// 末回合若还没通过，补一个"进行中…"药丸，让链条像过程、不孤零
function roundsView(ep) {
  const multi = ep.day_count > 1
  const out = ep.rounds.map((r) => ({
    label: multi ? fmtDay(r.day) : '尝试链',
    pills: chain(r.attempts),
  }))
  const last = out[out.length - 1]
  if (last && ep.outcome === '进行中') {
    const lp = last.pills[last.pills.length - 1]
    if (!lp || !lp.ok) last.pills.push({ label: '进行中…', pending: true })
  }
  return out
}

function fmtDay(d) {
  if (!d) return ''
  const [, m, day] = d.slice(0, 10).split('-')  // 兼容 "YYYY-MM-DD" 和完整 ISO 时间戳
  return `${+m}月${+day}日`
}
</script>

<template>
  <div v-if="error" class="panel error">{{ error }}</div>
  <div v-else-if="!data" class="panel">加载中…</div>
  <template v-else>
   <div class="tl-wrap">
    <!-- 安静上下文行：复习 + 思维默认值 并排（设计稿）-->
    <div class="ctx-row">
      <!-- 回头看看（间隔复习）-->
      <div v-if="reviewDue.length" class="ctx-card">
        <div class="ctx-head">
          <span class="ctx-title">回头看看</span>
          <span class="ctx-meta">{{ reviewDue.length }} 道到期</span>
        </div>
        <p class="ctx-sub">隔一阵回看一次，才会真正记牢。</p>
        <div class="rv-list">
          <button v-for="it in reviewDue" :key="it.pattern_id" class="rv-item" @click="startReview(it.pattern_id)">
            <span class="rv-name">{{ it.name }}</span>
            <span class="rv-foot">
              <span class="rv-meta">{{ catLabel(it.category) }} · {{ it.days_since }} 天前</span>
              <span class="rv-go">去复习 →</span>
            </span>
          </button>
        </div>
      </div>
      <!-- 你常见的思维默认值：镜子，非审判 -->
      <div class="ctx-card">
        <div class="ctx-title">你常见的思维默认值</div>
        <template v-if="data.thinking_patterns.enough">
          <div v-for="tp in data.thinking_patterns.items" :key="tp.id" class="tp">
            <div class="tp-name">{{ tp.name }}</div>
            <div class="tp-evidence">出现在 {{ tp.count }} 道题：{{ tp.members.join('、') }}</div>
            <div class="tp-advice">下次先问：{{ tp.advice }}</div>
          </div>
          <p v-if="data.persona.enough" class="persona-foot">{{ data.persona.line }}</p>
        </template>
        <p v-else class="note">{{ data.thinking_patterns.hint }}</p>
      </div>
    </div>

    <!-- 小标题 -->
    <div class="tl-heading">
      <h2>一道题，一段经历</h2>
      <span>从最近往回看</span>
    </div>

    <!-- 空态 -->
    <div v-if="!data.episodes.length" class="panel empty">
      还没有调试记录——去训练场闯一关，这里会长出你的成长轨迹。
    </div>

    <!-- 时间线：一道题 = 一段经历；最近一条为焦点 -->
    <div v-else class="timeline">
      <div v-for="(ep, ei) in data.episodes" :key="ep.pattern_id" :class="['node', { focal: ei === 0 }]">
        <span class="dot" />
        <div class="card">
          <!-- 标题=认知根因（记忆点），Bug 名缩成下面一行出处 -->
          <div class="card-head">
            <div class="head-main">
              <div class="title"><GlossaryText :text="ep.cognitive_root || ep.pattern_name" /></div>
              <div v-if="ep.cognitive_root" class="subtitle">{{ ep.pattern_name }}</div>
            </div>
            <span :class="['badge', ep.outcome]">{{ ep.outcome }}</span>
          </div>
          <div class="sub">
            调试 {{ ep.session_count }} 次 ·
            <template v-if="fmtDay(ep.first_at) !== fmtDay(ep.last_at)">
              第一次 {{ fmtDay(ep.first_at) }} · 最近 {{ fmtDay(ep.last_at) }}
            </template>
            <template v-else>{{ fmtDay(ep.last_at) }}</template>
          </div>

          <!-- 观察 / 猜测：统一文字小标 -->
          <div v-if="ep.observation" class="field">
            <span class="tag">观察</span><span class="field-val">{{ ep.observation }}</span>
          </div>
          <div v-if="ep.guess" class="field">
            <span class="tag">猜测</span><span class="field-val">{{ ep.guess }}</span>
          </div>
          <div v-if="ep.summary" class="field">
            <span class="tag summary-tag">总结</span><span class="field-val">{{ ep.summary }}</span>
          </div>

          <!-- 回合：按天分行的报错演变链 -->
          <div class="rounds">
            <div v-for="(r, ri) in roundsView(ep)" :key="ri" class="round">
              <span class="tag day">{{ r.label }}</span>
              <span class="link">
                <template v-for="(c, ci) in r.pills" :key="ci">
                  <span v-if="ci" class="arrow">→</span>
                  <span :class="['pill', { ok: c.ok, pending: c.pending }]">{{ c.label }}</span>
                </template>
              </span>
            </div>
          </div>

          <!-- 收获 -->
          <div v-for="(g, gi) in ep.gains" :key="gi" class="field">
            <span class="tag gain-tag">收获</span><span class="field-val">{{ g }}</span>
          </div>

          <button v-if="ep.session_id" class="replay-link"
                  @click="router.push(`/replay/${ep.session_id}`)">
            ▶ 回看这道题的解题过程
          </button>
        </div>
      </div>
    </div>
   </div>
  </template>
</template>

<style scoped>
.error { border-color: var(--red); color: var(--red); }
.note { color: var(--muted); font-size: 13.5px; line-height: 1.6; }
.replay-link {
  margin-top: 12px; background: none; border: 1px solid var(--border); color: var(--primary);
  border-radius: 999px; padding: 6px 14px; font-size: 13px; cursor: pointer; font-family: inherit;
}
.replay-link:hover { border-color: var(--primary); background: var(--accent-soft); }
.tl-wrap { max-width: 760px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }

/* 安静上下文行：复习 + 思维默认值 并排（设计稿）*/
.ctx-row { display: flex; gap: 14px; flex-wrap: wrap; }
.ctx-card { flex: 1; min-width: 280px; background: var(--panel); border: 1px solid var(--border); border-radius: 13px; padding: 15px 17px; }
.ctx-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 4px; }
.ctx-title { font-family: var(--serif); font-size: 15px; font-weight: 600; color: var(--text); }
.ctx-meta { font-size: 12px; color: var(--muted); }
.ctx-sub { margin: 0 0 11px; font-size: 12.5px; color: var(--muted); line-height: 1.6; }
.rv-list { display: flex; flex-direction: column; gap: 7px; }
.rv-item { display: flex; flex-direction: column; gap: 4px; width: 100%; text-align: left; background: var(--accent-soft); border: 1px solid var(--border); border-radius: 9px; padding: 9px 12px; cursor: pointer; font: inherit; transition: border-color 0.15s; }
.rv-item:hover { border-color: var(--primary); }
.rv-name { font-size: 13.5px; font-weight: 600; color: var(--text); line-height: 1.4; }
.rv-foot { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.rv-meta { font-size: 11.5px; color: var(--muted); }
.rv-go { font-size: 12px; color: var(--primary-dark); white-space: nowrap; }
.tp { border-left: 2px solid #d6aa91; padding-left: 11px; margin-bottom: 12px; }
.tp:last-of-type { margin-bottom: 0; }
.tp-name { font-size: 13.5px; font-weight: 600; color: var(--text); }
.tp-evidence { font-size: 12px; color: var(--muted); margin-top: 3px; }
.tp-reflection { font-size: 12px; color: var(--text); margin-top: 5px; line-height: 1.5; }
.tp-advice { font-size: 12.5px; color: var(--primary-dark); margin-top: 5px; }
.persona-foot { margin: 10px 0 0; font-size: 12.5px; color: var(--muted); line-height: 1.6; }

/* 小标题 */
.tl-heading { display: flex; align-items: baseline; gap: 10px; margin-top: 8px; }
.tl-heading h2 { font-family: var(--serif); font-size: 19px; font-weight: 600; color: var(--text); margin: 0; }
.tl-heading span { font-size: 13px; color: var(--muted); }

.empty { color: var(--muted); text-align: center; padding: 40px 20px; }

/* 竖向时间线：最近一条为焦点 */
.timeline { position: relative; padding-left: 30px; }
.timeline::before { content: ''; position: absolute; left: 9px; top: 8px; bottom: 8px; width: 2px; background: var(--border); }
.node { position: relative; margin-bottom: 18px; }
.dot { position: absolute; left: -26px; top: 20px; width: 9px; height: 9px; border-radius: 50%; background: #c8a48c; border: 2px solid var(--bg); }
.node.focal .dot { left: -29px; top: 22px; width: 14px; height: 14px; background: var(--primary); border: 3px solid var(--bg); box-shadow: 0 0 0 3px rgba(193,95,60,0.18); }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; }
.node.focal .card { background: #fff; border-color: #f0d8c8; border-left: 3px solid var(--primary); box-shadow: 0 14px 30px -18px rgba(193,95,60,0.3); }
.card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.head-main { min-width: 0; }
.title { font-family: var(--serif); font-size: 16px; font-weight: 600; line-height: 1.45; color: var(--text); }
.subtitle { font-size: 12.5px; color: var(--muted); margin-top: 3px; }
.sub { font-size: 12.5px; color: var(--muted); margin-top: 8px; }
.badge { font-size: 12px; padding: 3px 11px; border-radius: 999px; white-space: nowrap; margin-top: 2px; }
.badge.进行中 { background: #f3ecd6; color: #87651f; }
.badge.已解决 { background: var(--accent-soft); color: var(--primary-dark); }
.badge.已内化 { background: #e4ede0; color: #3f5837; }
.field { display: flex; gap: 12px; margin-top: 9px; font-size: 13.5px; line-height: 1.55; align-items: baseline; }
.tag { font-size: 12px; color: var(--muted); min-width: 40px; flex-shrink: 0; }
.field-val { color: var(--text); flex: 1; min-width: 0; }
.gain-tag { color: #6f8a64; }
.summary-tag { color: var(--primary-dark); }
.rounds { margin-top: 9px; display: flex; flex-direction: column; gap: 6px; }
.round { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.day { min-width: 60px; }
.link { display: inline-flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.pill { font-size: 11.5px; padding: 1px 8px; border-radius: 6px; background: #f1e3de; color: #9a6a58; }
.pill.ok { background: #e7eee3; color: #4d6244; }
.pill.pending { background: #ece6da; color: var(--muted); }
.arrow { color: #cfc6b5; font-size: 11px; }
</style>
