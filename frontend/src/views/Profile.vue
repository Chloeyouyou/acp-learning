<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'
import RadarChart from '../components/RadarChart.vue'

const ZH = {
  Log_Reading: '日志阅读', Boundary_Awareness: '边界意识', Root_Cause_Reasoning: '根因分析',
  Independent_Debug: '独立调试', Hypothesis_Testing: '假设验证', Internalization: '内化',
  AI_Review: 'AI代码审查', AI_Verification: 'AI回答验证', Prompt_Design: '提示词设计',
}

const profile = ref(null)
const error = ref('')
const expanded = ref(null) // capability name
const events = ref([])
const loadingEvents = ref(false)

onMounted(load)

async function load() {
  try {
    profile.value = await api.getProfile()
  } catch (e) {
    error.value = '加载失败：' + e.message
  }
}

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
</script>

<template>
  <div v-if="error" class="panel error">{{ error }}</div>
  <div v-else-if="!profile" class="panel">加载中…</div>
  <div v-else class="layout">
    <div class="panel radar-panel">
      <h3>能力画像</h3>
      <p class="note">画像的每个数字都有出处——点击右侧能力项可下钻到具体事件与证据。</p>
      <RadarChart :dimensions="profile.dimensions" />
      <div class="legend">
        <span class="dot low" /> 灰色分数 = 数据不足（事件少于5个）
      </div>
    </div>

    <div class="right-col">
      <div class="panel">
        <h3>能力向量</h3>
        <div v-if="!Object.keys(profile.vector).length" class="note">
          还没有任何能力事件——去训练场完成一关吧。
        </div>
        <div v-for="(v, cap) in profile.vector" :key="cap" class="cap-row">
          <button class="cap-head" @click="drill(cap)">
            <span class="cap-name">{{ ZH[cap] || cap }} <small>{{ cap }}</small></span>
            <span class="bar"><span class="fill" :style="{ width: v.score + '%' }" /></span>
            <span class="cap-score" :class="{ low: v.confidence === 'low' }">
              {{ v.score }}<small>（{{ v.events_count }}事件）</small>
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
        <div v-if="!profile.knowledge_states.length" class="note">暂无记录。</div>
        <table v-else class="ks-table">
          <thead>
            <tr><th>Bug模式</th><th>知识点</th><th>状态</th></tr>
          </thead>
          <tbody>
            <tr v-for="s in profile.knowledge_states" :key="s.pattern_id">
              <td class="mono">{{ s.pattern_id }}</td>
              <td>{{ s.knowledge_points.join('、') }}</td>
              <td><span :class="['state', s.state]">{{ s.state }}</span></td>
            </tr>
          </tbody>
        </table>
        <p class="note">「已解决」= 在AI帮助下修复过；「已内化」= 能独立解释成因并通过变式验证（V0.3开放）。</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.error { border-color: var(--red); color: var(--red); }
.layout { display: grid; grid-template-columns: 380px 1fr; gap: 16px; align-items: start; }
.radar-panel { display: flex; flex-direction: column; align-items: center; }
.radar-panel h3 { align-self: flex-start; }
h3 { margin-top: 0; }
.note { color: var(--muted); font-size: 13px; }
.legend { font-size: 12px; color: var(--muted); margin-top: 8px; }
.dot.low { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }

.right-col { display: flex; flex-direction: column; gap: 16px; }
.cap-row { border-bottom: 1px solid var(--border); }
.cap-row:last-child { border-bottom: none; }
.cap-head {
  display: grid; grid-template-columns: 200px 1fr 110px; gap: 12px; align-items: center;
  width: 100%; border: none; background: none; padding: 10px 4px; text-align: left;
}
.cap-head:hover { background: #f8fafc; }
.cap-name { font-weight: 600; font-size: 14px; }
.cap-name small { display: block; font-weight: 400; color: var(--muted); font-family: Consolas, monospace; }
.bar { height: 8px; background: #eef1f5; border-radius: 4px; overflow: hidden; }
.fill { display: block; height: 100%; background: var(--primary); border-radius: 4px; }
.cap-score { font-weight: 700; color: var(--primary); text-align: right; }
.cap-score.low { color: var(--muted); }
.cap-score small { font-weight: 400; color: var(--muted); }

.events { padding: 4px 4px 12px 16px; display: flex; flex-direction: column; gap: 8px; }
.event { display: flex; gap: 10px; align-items: flex-start; }
.delta {
  font-weight: 700; font-size: 13px; min-width: 28px; text-align: center;
  border-radius: 6px; padding: 2px 4px;
}
.delta.pos { background: #dcfce7; color: var(--green); }
.delta.neg { background: #fee2e2; color: var(--red); }
.evidence { font-size: 13px; }
.meta { font-size: 12px; color: var(--muted); }

.ks-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.ks-table th, .ks-table td { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--border); }
.ks-table th { color: var(--muted); font-weight: 600; font-size: 13px; }
.mono { font-family: Consolas, monospace; font-size: 13px; }
.state { font-size: 12px; padding: 2px 10px; border-radius: 999px; background: #f1f5f9; }
.state.已接触 { background: #fef9c3; color: #854d0e; }
.state.已解决 { background: #dbeafe; color: #1e40af; }
.state.已内化 { background: #dcfce7; color: #166534; }
</style>
