<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'
import GlossaryText from '../components/GlossaryText.vue'

const data = ref(null)
const error = ref('')

onMounted(async () => {
  try {
    data.value = await api.getTimeline()
  } catch (e) {
    error.value = '加载失败：' + e.message
  }
})

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
    <!-- 跨题思维默认值：镜子，非审判、非榜单 -->
    <div class="persona">
      <h3>你最近常见的思维默认值</h3>
      <template v-if="data.thinking_patterns.enough">
        <div v-for="tp in data.thinking_patterns.items" :key="tp.id" class="tp">
          <div class="tp-name">{{ tp.name }}</div>
          <div class="tp-evidence">出现在 {{ tp.count }} 道题：{{ tp.members.join('、') }}</div>
          <div class="tp-advice">下次先问自己：{{ tp.advice }}</div>
        </div>
        <p v-if="data.persona.enough" class="persona-foot">{{ data.persona.line }}</p>
      </template>
      <p v-else class="note">{{ data.thinking_patterns.hint }}</p>
    </div>

    <!-- 空态 -->
    <div v-if="!data.episodes.length" class="panel empty">
      还没有调试记录——去训练场闯一关，这里会长出你的成长轨迹。
    </div>

    <!-- 时间线：一道题 = 一段经历 -->
    <div v-else class="timeline">
      <div v-for="ep in data.episodes" :key="ep.pattern_id" class="node">
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
        </div>
      </div>
    </div>
  </template>
</template>

<style scoped>
.error { border-color: var(--red); color: var(--red); }

/* 调试人格卡 */
.persona {
  background: var(--panel); border: 1px solid var(--border); border-radius: 14px;
  padding: 18px 22px; box-shadow: 0 1px 2px rgba(43,41,36,0.03); margin-bottom: 22px;
}
.persona h3 { margin: 0 0 12px; font-size: 17px; }
.note { color: var(--muted); font-size: 13.5px; line-height: 1.6; }

/* 思维默认值：一条条镜子，不排名不评分 */
.tp { padding: 10px 0; border-top: 1px solid var(--border); }
.tp:first-of-type { border-top: none; padding-top: 0; }
.tp-name { font-family: var(--serif); font-size: 15px; font-weight: 600; color: var(--text); }
.tp-evidence { font-size: 12.5px; color: var(--muted); margin-top: 4px; }
.tp-advice { font-size: 13px; color: var(--primary-dark); margin-top: 5px; }
.persona-foot { margin: 12px 0 0; font-size: 13px; color: var(--muted); line-height: 1.6; }

.empty { color: var(--muted); text-align: center; padding: 40px 20px; }

/* 竖向时间线 */
.timeline { position: relative; padding-left: 26px; }
.timeline::before {
  content: ''; position: absolute; left: 7px; top: 6px; bottom: 6px;
  width: 2px; background: var(--border);
}
.node { position: relative; margin-bottom: 20px; }
.dot {
  position: absolute; left: -25px; top: 19px; width: 9px; height: 9px;
  border-radius: 50%; background: var(--primary); border: 2px solid var(--bg);
}
.card {
  background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
  padding: 16px 18px; box-shadow: 0 1px 2px rgba(43,41,36,0.04);
}
.card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.head-main { min-width: 0; }
.title { font-family: var(--serif); font-size: 16px; font-weight: 600; line-height: 1.45; }
.subtitle { font-size: 12.5px; color: var(--muted); margin-top: 3px; }
.sub { font-size: 12.5px; color: var(--muted); margin-top: 8px; }
.badge { margin-top: 2px; }

.badge { font-size: 12px; padding: 3px 11px; border-radius: 999px; white-space: nowrap; }
.badge.进行中 { background: #f3ecd6; color: #87651f; }
.badge.已解决 { background: var(--accent-soft); color: var(--primary-dark); }
.badge.已内化 { background: #e4ede0; color: #3f5837; }

/* 统一文字小标体系：观察 / 猜测 / 收获 / 日期 同款克制标签 */
.field { display: flex; gap: 12px; margin-top: 9px; font-size: 13.5px; line-height: 1.55; align-items: baseline; }
.tag { font-size: 12px; color: var(--muted); letter-spacing: 0.5px; min-width: 40px; flex-shrink: 0; }
.field-val { color: var(--text); flex: 1; min-width: 0; }
.gain-tag { color: #6f8a64; }

.rounds { margin-top: 9px; display: flex; flex-direction: column; gap: 6px; }
.round { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.day { min-width: 60px; }
.link { display: inline-flex; align-items: center; gap: 5px; flex-wrap: wrap; }
/* 报错链当配角：字号小、颜色收敛，不和认知根因抢镜 */
.pill {
  font-size: 11.5px; padding: 1px 8px; border-radius: 6px;
  background: #f1e3de; color: #9a6a58;
}
.pill.ok { background: #e7eee3; color: #4d6244; }
.pill.pending { background: #ece6da; color: var(--muted); }
.arrow { color: #cfc6b5; font-size: 11px; }
</style>
