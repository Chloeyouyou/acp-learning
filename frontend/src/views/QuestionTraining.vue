<script setup>
import { ref, computed } from 'vue'
import { api } from '../api'

// 预置场景（id 与后端 question_training.SCENARIOS 对齐）
const SCENARIOS = [
  { id: 'login', title: '登录功能跑不通', brief: '你在做一个登录功能，点登录后没反应或报错。把这件事问清楚，让 AI 能直接帮上忙。' },
  { id: 'list_empty', title: '列表页一直空白', brief: '你的页面应该显示一个列表，但运行后一直是空白，数据出不来。' },
  { id: 'wrong_result', title: '函数算出来的结果不对', brief: '你写了个函数做计算，但它返回的数和你预期的对不上。' },
]

const scenarioId = ref(SCENARIOS[0].id)
const scenario = computed(() => SCENARIOS.find((s) => s.id === scenarioId.value))

const draft = ref('')
const loading = ref(false)
const error = ref('')
const result = ref(null)       // { phenomenon, context, expectation, score, feedback, confidence, degraded }
const prevScore = ref(null)    // 上一版分数（用于显示进步）
const attempts = ref(0)        // 改了几版

function pickScenario(id) {
  if (id === scenarioId.value) return
  scenarioId.value = id
  // 换场景重置诊断（提问内容也清空，避免对不上）
  draft.value = ''
  result.value = null
  prevScore.value = null
  attempts.value = 0
  error.value = ''
}

async function submit() {
  const p = draft.value.trim()
  if (!p || loading.value) return
  loading.value = true
  error.value = ''
  try {
    const r = await api.diagnoseQuestion(scenarioId.value, p)
    prevScore.value = result.value ? result.value.score : null
    result.value = r
    attempts.value += 1
  } catch (e) {
    error.value = e.message || '诊断失败，请稍后再试'
  } finally {
    loading.value = false
  }
}

const scoreColor = computed(() => {
  const s = result.value?.score ?? 0
  return s >= 80 ? '#5c7a52' : s >= 45 ? 'var(--primary)' : '#a89e8c'
})
const factors = computed(() => {
  const r = result.value
  return [
    { key: '现象', desc: '报了什么、看到什么', ok: !!r?.phenomenon },
    { key: '上下文', desc: '哪段代码、哪一行', ok: !!r?.context },
    { key: '预期', desc: '你本来想要什么结果', ok: !!r?.expectation },
  ]
})
const scoreDelta = computed(() => {
  if (result.value == null || prevScore.value == null) return null
  return result.value.score - prevScore.value
})
</script>

<template>
  <div class="qt">
    <div class="qt-header">
      <h2>把问题问清楚，AI 才帮得上</h2>
      <p>同样一件事，问得越清楚，AI 越能直接帮到点子上。选一个场景，试着把你的提问写出来——知返只看你「问得好不好」，不替你解题。</p>
    </div>

    <!-- 场景选择 -->
    <div class="qt-scenarios">
      <button v-for="s in SCENARIOS" :key="s.id"
              :class="['qt-sc', { on: s.id === scenarioId }]" @click="pickScenario(s.id)">
        {{ s.title }}
      </button>
    </div>

    <div class="qt-grid">
      <!-- 左：写提问 + 对照 -->
      <div class="qt-left">
        <div class="panel">
          <div class="qt-promptbar">
            <span class="qt-promptlabel">你向 AI 的提问</span>
            <span class="qt-lvl">{{ scenario.title }}</span>
          </div>
          <p class="qt-brief">{{ scenario.brief }}</p>
          <textarea
            v-model="draft" class="qt-input" rows="5"
            placeholder="比如：写清楚报了什么错、在哪段代码、你本来想要什么结果…"
            @keydown.ctrl.enter="submit"
          />
          <div class="qt-ctrl">
            <button class="qt-next" :disabled="!draft.trim() || loading" @click="submit">
              {{ loading ? '知返诊断中…' : result ? '再改一版 →' : '让知返看看 →' }}
            </button>
            <span v-if="attempts" class="qt-step">已改 {{ attempts }} 版</span>
          </div>
          <p v-if="error" class="qt-error">{{ error }}</p>
        </div>

        <div class="panel qt-compare">
          <div class="qt-compare-t">对照：同一件事的两种问法</div>
          <div class="qt-compare-row">
            <div class="qt-eg-card bad">
              <div class="qt-eg-tag bad">✗ 差</div>
              <div class="qt-eg-text">代码报错了</div>
            </div>
            <div class="qt-eg-card good">
              <div class="qt-eg-tag good">✓ 好</div>
              <div class="qt-eg-text">登录报 NullPointerException，在 UserService 第 32 行，期望完成登录。</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 右（焦点）：知返提问诊断 -->
      <div class="qt-diag">
        <div class="qt-diag-head">
          <span class="qt-ava">知</span>
          <div>
            <div class="qt-diag-name">知返 · 提问诊断</div>
            <div class="qt-diag-sub">现象 + 上下文 + 预期</div>
          </div>
        </div>

        <!-- 空态：还没提交 -->
        <div v-if="!result" class="qt-empty">
          在左边写下你的提问，点「让知返看看」——它会告诉你这条提问缺了哪个要素、怎么补。
        </div>

        <template v-else>
          <div class="qt-score">
            <span class="qt-score-n" :style="{ color: scoreColor }">{{ result.score }}</span>
            <span class="qt-score-u">/ 100 提问分</span>
            <span v-if="scoreDelta != null && scoreDelta !== 0"
                  :class="['qt-delta', scoreDelta > 0 ? 'up' : 'down']">
              {{ scoreDelta > 0 ? '↑ +' + scoreDelta : '↓ ' + scoreDelta }}
            </span>
          </div>
          <div class="qt-bar"><div class="qt-bar-f" :style="{ width: result.score + '%', background: scoreColor }" /></div>
          <div class="qt-factors">
            <div v-for="f in factors" :key="f.key" :class="['qt-f', f.ok ? 'ok' : 'no']">
              <div class="qt-f-head">
                <span class="qt-f-icon">{{ f.ok ? '✓' : '○' }}</span>
                <span class="qt-f-name">{{ f.key }}</span>
                <span class="qt-f-desc">{{ f.desc }}</span>
              </div>
            </div>
          </div>
          <div class="qt-msg">{{ result.feedback }}</div>
          <p v-if="result.degraded" class="qt-degraded">（知返暂时离线，以上为本地提示）</p>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.qt { max-width: 1040px; margin: 0 auto; }
.qt-header { margin-bottom: 16px; }
.qt-header h2 { font-family: var(--serif); font-size: 20px; font-weight: 600; color: var(--text); margin: 0 0 6px; }
.qt-header p { font-size: 14px; color: var(--muted); line-height: 1.7; margin: 0; max-width: 660px; }

.qt-scenarios { display: flex; gap: 9px; flex-wrap: wrap; margin-bottom: 18px; }
.qt-sc { font: inherit; font-size: 13px; color: var(--muted); background: var(--panel); border: 1px solid var(--border); border-radius: 999px; padding: 7px 15px; cursor: pointer; transition: all 0.15s; }
.qt-sc:hover { color: var(--text); border-color: #dac9b8; }
.qt-sc.on { color: #fff; background: var(--primary); border-color: var(--primary); }

.qt-grid { display: grid; grid-template-columns: 1fr 400px; gap: 18px; align-items: start; }
@media (max-width: 820px) { .qt-grid { grid-template-columns: 1fr; } }
.qt-left { display: flex; flex-direction: column; gap: 14px; }
.panel { background: var(--panel); border: 1px solid var(--border); border-radius: 13px; padding: 18px 20px; }

.qt-promptbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.qt-promptlabel { font-size: 13.5px; font-weight: 600; color: var(--text); }
.qt-lvl { font-size: 12px; color: var(--muted); }
.qt-brief { font-size: 12.5px; color: var(--muted); line-height: 1.6; margin: 0 0 12px; }
.qt-input {
  width: 100%; box-sizing: border-box; background: #fff; border: 1px solid #e2dccd; border-radius: 11px;
  padding: 13px 15px; font-family: inherit; font-size: 14px; line-height: 1.7; color: var(--text); resize: vertical; outline: none;
}
.qt-input:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(193, 95, 60, 0.10); }
.qt-input::placeholder { color: #b3ab9a; }
.qt-ctrl { display: flex; align-items: center; gap: 12px; margin-top: 14px; }
.qt-next { font: inherit; font-size: 13px; font-weight: 700; color: #fff; background: var(--primary); border: none; border-radius: 9px; padding: 10px 20px; cursor: pointer; }
.qt-next:disabled { opacity: 0.5; cursor: not-allowed; }
.qt-step { font-size: 12.5px; color: var(--muted); }
.qt-error { margin: 10px 0 0; font-size: 12.5px; color: #a54e30; }

.qt-compare-t { font-size: 12.5px; font-weight: 600; color: var(--muted); margin-bottom: 9px; }
.qt-compare-row { display: flex; gap: 12px; }
.qt-eg-card { flex: 1; border-radius: 10px; padding: 11px 13px; }
.qt-eg-card.bad { background: #fbf3ef; border: 1px solid #f0d8c8; }
.qt-eg-card.good { background: #f3f7f0; border: 1px solid #d8e4d0; }
.qt-eg-tag { font-size: 11.5px; font-weight: 600; margin-bottom: 5px; }
.qt-eg-tag.bad { color: #a54e30; }
.qt-eg-tag.good { color: #5c7a52; }
.qt-eg-text { font-family: 'IBM Plex Mono', monospace; font-size: 12.5px; line-height: 1.5; color: #6f695d; }

/* 焦点：诊断卡 */
.qt-diag { background: #fff; border: 1px solid #f0d8c8; border-radius: 14px; padding: 20px; box-shadow: 0 16px 36px -20px rgba(193, 95, 60, 0.32); }
.qt-diag-head { display: flex; align-items: center; gap: 11px; margin-bottom: 16px; }
.qt-ava { width: 34px; height: 34px; border-radius: 50%; background: var(--primary); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-weight: 700; flex: none; }
.qt-diag-name { font-size: 15px; font-weight: 700; color: var(--text); line-height: 1; }
.qt-diag-sub { font-size: 12px; color: var(--muted); margin-top: 3px; }
.qt-empty { font-size: 13.5px; color: var(--muted); line-height: 1.7; padding: 8px 0; }

.qt-score { display: flex; align-items: baseline; gap: 8px; margin-bottom: 6px; }
.qt-score-n { font-family: var(--serif); font-size: 38px; font-weight: 600; line-height: 1; }
.qt-score-u { font-size: 13px; color: var(--muted); }
.qt-delta { font-size: 12.5px; font-weight: 600; margin-left: auto; }
.qt-delta.up { color: #5c7a52; }
.qt-delta.down { color: #a89e8c; }
.qt-bar { height: 8px; background: #ece6da; border-radius: 999px; overflow: hidden; margin-bottom: 18px; }
.qt-bar-f { height: 100%; border-radius: 999px; transition: width 0.35s ease; }
.qt-factors { display: flex; flex-direction: column; gap: 10px; }
.qt-f { border-radius: 11px; padding: 12px 14px; }
.qt-f.ok { background: #f3f7f0; border: 1px solid #d8e4d0; }
.qt-f.no { background: #fbf3ef; border: 1px solid #f0d8c8; }
.qt-f-head { display: flex; align-items: center; gap: 8px; }
.qt-f-icon { font-size: 14px; }
.qt-f.ok .qt-f-icon { color: #5c7a52; }
.qt-f.no .qt-f-icon { color: #a89e8c; }
.qt-f-name { font-size: 14px; font-weight: 600; color: var(--text); }
.qt-f-desc { font-size: 12px; color: var(--muted); margin-left: auto; }
.qt-msg { margin-top: 16px; padding-top: 15px; border-top: 1px solid #f1e8da; font-size: 13.5px; line-height: 1.7; color: var(--text); }
.qt-degraded { margin: 8px 0 0; font-size: 11.5px; color: #a89e8c; }
</style>
