<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import GlossaryText from '../components/GlossaryText.vue'
import { nextActionEyebrow, nextActionQueueHint, nextActionTarget } from '../learning-path'

const router = useRouter()
const data = ref(null)
const error = ref('')
const guidance = ref(null)
const guidanceLoaded = ref(false)

onMounted(async () => {
  const [timeline, next] = await Promise.allSettled([
    api.getTimeline(), api.getNextAction(),
  ])
  if (timeline.status === 'fulfilled') data.value = timeline.value
  else error.value = '加载失败：' + timeline.reason.message
  if (next.status === 'fulfilled') guidance.value = next.value
  guidanceLoaded.value = true
})

const nextStep = computed(() => guidance.value?.action || {
  kind: 'start', title: '完成一次真实调试',
  detail: '亲自运行、判断和修改，第一条成长证据就从这里开始。', cta: '开始练习',
})
const nextEyebrow = computed(() => nextActionEyebrow(guidance.value))
const queuedHint = computed(() => nextActionQueueHint(guidance.value))

// 近 7 天调试足迹（镜子非审判）：进步和松动先讲，卡点用四步语言、带一句可行建议
const footprintLines = computed(() => {
  const fp = data.value?.footprint
  if (!fp?.enough) return []
  const lines = []
  if (fp.targeted_progress?.length)
    lines.push({ tag: '进步', good: true, text: `在《${fp.targeted_progress.join('》《')}》里，你从到处试改，走到了对准关键行修改。` })
  if (fp.loosened?.length)
    lines.push({ tag: '松动', good: true, text: `「${fp.loosened[0].name}」这个思维默认值，这周在《${fp.loosened[0].pattern}》上松动了。` })
  if (fp.stuck_step)
    lines.push({ tag: '卡点', good: false, text: `这周最常需要搭把手的一步是「${fp.stuck_step}」（${fp.stuck_count} 次）——下次卡在这里时，先回看运行结果再动手。` })
  return lines
})

function takeNextStep() {
  router.push(nextActionTarget(guidance.value))
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
    <header class="growth-head">
      <div class="growth-title">
        <span class="growth-eyebrow">我的成长</span>
        <h1>每一次想通，都有证据</h1>
        <p>这里不只记“做对了几题”，还会留下你亲自运行、修改和解释的过程。</p>
      </div>
      <RouterLink to="/profile" class="profile-link">查看能力画像 →</RouterLink>
      <div class="evidence-path" aria-label="成长证据链">
        <div><b>1</b><span><strong>真实动作</strong><small>运行、修改、提交</small></span></div>
        <i>→</i>
        <div><b>2</b><span><strong>关键转折</strong><small>从卡住到找对方向</small></span></div>
        <i>→</i>
        <div><b>3</b><span><strong>内化经验</strong><small>下次能自己迁移</small></span></div>
      </div>
    </header>

    <!-- 下一步 + 长期发现：行动始终只有一个，归纳不抢选择。 -->
    <div class="ctx-row">
      <div class="ctx-card next-card" aria-label="唯一下一步">
        <span class="ctx-kicker">下一步</span>
        <p v-if="!guidanceLoaded" class="note">正在整理最适合接着做的一步…</p>
        <template v-else>
          <span class="next-eyebrow">{{ nextEyebrow }}</span>
          <div class="next-title">{{ nextStep.title }}</div>
          <p class="ctx-sub">{{ nextStep.detail }}</p>
          <button class="next-action" @click="takeNextStep">{{ nextStep.cta }} →</button>
          <p v-if="queuedHint" class="queued-hint">{{ queuedHint }}</p>
        </template>
      </div>
      <!-- 你常见的思维默认值：镜子，非审判 -->
      <div class="ctx-card">
        <span class="ctx-kicker">长期发现</span>
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

    <!-- 近 7 天调试足迹：只在有活动时出现，安静一条 -->
    <div v-if="data.footprint?.enough" class="footprint" aria-label="近7天调试足迹">
      <div class="fp-head">
        <span class="ctx-kicker">近 {{ data.footprint.days }} 天足迹</span>
        <span class="fp-stats">
          练了 {{ data.footprint.patterns_touched }} 道题 · 尝试 {{ data.footprint.attempts }} 次 ·
          活跃 {{ data.footprint.active_days }} 天<template v-if="data.footprint.internalized.length"> · 内化 {{ data.footprint.internalized.length }} 道</template>
        </span>
      </div>
      <div v-for="(l, li) in footprintLines" :key="li" class="field">
        <span :class="['tag', { 'gain-tag': l.good }]">{{ l.tag }}</span>
        <span class="field-val">{{ l.text }}</span>
      </div>
    </div>

    <!-- 小标题 -->
    <div class="tl-heading">
      <h2>过程记录</h2>
      <span>一道题，一段从尝试到想通的经历</span>
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
.growth-head {
  display: grid; grid-template-columns: 1fr auto; gap: 16px 24px; padding: 6px 0 12px;
}
.growth-eyebrow, .ctx-kicker { display: block; color: var(--primary); font-size: 11px; font-weight: 700; letter-spacing: .1em; }
.growth-title h1 { margin: 6px 0 7px; font-size: 27px; }
.growth-title p { margin: 0; max-width: 560px; color: var(--muted); font-size: 13.5px; line-height: 1.7; }
.profile-link { align-self: start; color: var(--muted); font-size: 13px; text-decoration: none; padding: 7px 0; }
.profile-link:hover { color: var(--primary); }
.evidence-path {
  grid-column: 1 / -1; display: flex; align-items: center; gap: 12px; padding: 13px 15px;
  background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
}
.evidence-path > div { flex: 1; min-width: 0; display: flex; align-items: center; gap: 9px; }
.evidence-path b { width: 25px; height: 25px; display: inline-flex; align-items: center; justify-content: center; flex: none; border-radius: 50%; background: var(--accent-soft); color: var(--primary-dark); font-size: 12px; }
.evidence-path span { display: flex; flex-direction: column; gap: 2px; }
.evidence-path strong { font-family: var(--serif); font-size: 13.5px; }
.evidence-path small { color: var(--muted); font-size: 11.5px; }
.evidence-path i { color: #cfc6b5; font-style: normal; }

/* 安静上下文行：复习 + 思维默认值 并排（设计稿）*/
.ctx-row { display: flex; gap: 14px; flex-wrap: wrap; }
.ctx-card { flex: 1; min-width: 280px; background: var(--panel); border: 1px solid var(--border); border-radius: 13px; padding: 15px 17px; }
.ctx-kicker { margin-bottom: 6px; }
.ctx-title { font-family: var(--serif); font-size: 15px; font-weight: 600; color: var(--text); }
.ctx-sub { margin: 0 0 11px; font-size: 12.5px; color: var(--muted); line-height: 1.6; }
.next-card { border-color: #dcc5b4; background: #fbf6ef; }
.next-eyebrow { display: block; margin: 8px 0 4px; color: var(--primary-dark); font-size: 11.5px; }
.next-title { font-family: var(--serif); font-size: 17px; font-weight: 600; color: var(--text); margin-bottom: 5px; }
.next-action { border: 0; border-radius: 9px; padding: 8px 14px; background: var(--primary); color: white; font: inherit; font-size: 13px; cursor: pointer; }
.next-action:hover { background: var(--primary-dark); }
.queued-hint { margin: 9px 0 0; color: var(--muted); font-size: 11.5px; }
.tp { border-left: 2px solid #d6aa91; padding-left: 11px; margin-bottom: 12px; }
.tp:last-of-type { margin-bottom: 0; }
.tp-name { font-size: 13.5px; font-weight: 600; color: var(--text); }
.tp-evidence { font-size: 12px; color: var(--muted); margin-top: 3px; }
.tp-reflection { font-size: 12px; color: var(--text); margin-top: 5px; line-height: 1.5; }
.tp-advice { font-size: 12.5px; color: var(--primary-dark); margin-top: 5px; }
.persona-foot { margin: 10px 0 0; font-size: 12.5px; color: var(--muted); line-height: 1.6; }

/* 近 7 天足迹：安静一条，不与「下一步」抢焦点 */
.footprint { background: var(--panel); border: 1px solid var(--border); border-radius: 13px; padding: 14px 17px; }
.fp-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.fp-stats { font-size: 13px; color: var(--text); }

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
@media (max-width: 640px) {
  .growth-head { grid-template-columns: 1fr; }
  .profile-link { justify-self: start; }
  .evidence-path { flex-direction: column; align-items: stretch; }
  .evidence-path i { transform: rotate(90deg); align-self: center; }
}
</style>
