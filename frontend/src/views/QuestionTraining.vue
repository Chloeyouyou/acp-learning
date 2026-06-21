<script setup>
import { ref, computed } from 'vue'

// 自包含的 3 步互动：把同一个提问从「差」一步步补成「三要素齐全」（设计稿，前端写死，无后端）
const L = [
  {
    prompt: '代码报错了',
    s1: false, s2: false, s3: false,
    s1Hint: '没说报了什么错、出现什么现象。',
    s2Hint: '没说是哪段代码、哪个文件。',
    s3Hint: '没说你期望发生什么。',
    score: 18,
    msg: '这样问，AI 只能猜。它不知道哪段代码、报了什么、你想要什么——补一个要素试试。',
  },
  {
    prompt: '登录功能报错了，提示 NullPointerException。',
    s1: true, s2: false, s3: false,
    s1Hint: '说清了报错类型，AI 能对上号了。',
    s2Hint: '还差：错在哪个文件 / 第几行？',
    s3Hint: '还差：你本来期望它做什么？',
    score: 52,
    msg: '好多了——现象说清了。再告诉 AI「错在哪里」，它就能精准定位。',
  },
  {
    prompt: '登录功能报 NullPointerException，出错在 UserService 第 32 行，\n我期望它完成登录并返回用户信息。',
    s1: true, s2: true, s3: true,
    s1Hint: '现象明确：NullPointerException。',
    s2Hint: '定位明确：UserService 第 32 行。',
    s3Hint: '预期明确：完成登录、返回用户信息。',
    score: 90,
    msg: '这就是一个 AI 能直接帮上忙的提问——现象、上下文、预期三要素齐了，AI 不用猜就能帮到点子上。',
  },
]

const level = ref(0)
const cur = computed(() => L[level.value])
const stepNo = computed(() => level.value + 1)
const levelLabel = computed(() => ['初稿', '补了现象', '三要素齐全'][level.value])
const nextLabel = computed(() => (level.value < 2 ? '补一个要素 →' : '重新开始'))
const scoreColor = computed(() => (cur.value.score >= 80 ? '#5c7a52' : cur.value.score >= 45 ? 'var(--primary)' : '#a89e8c'))
const factors = computed(() => [
  { key: '现象', desc: '报了什么、看到什么', ok: cur.value.s1, hint: cur.value.s1Hint },
  { key: '上下文', desc: '哪个文件、哪一行', ok: cur.value.s2, hint: cur.value.s2Hint },
  { key: '预期', desc: '你本来想要什么结果', ok: cur.value.s3, hint: cur.value.s3Hint },
])
function next() { level.value = level.value >= 2 ? 0 : level.value + 1 }
function back() { level.value = Math.max(0, level.value - 1) }
</script>

<template>
  <div class="qt">
    <div class="qt-header">
      <h2>把问题问清楚，AI 才帮得上</h2>
      <p>场景：你的登录功能跑不通。同样一件事，问得越清楚，AI 越能直接帮到点子上。试着把提问一步步补全。</p>
    </div>

    <div class="qt-grid">
      <!-- 左：正在写的提问 + 对照 -->
      <div class="qt-left">
        <div class="panel">
          <div class="qt-promptbar">
            <span class="qt-promptlabel">你向 AI 的提问</span>
            <span class="qt-lvl">{{ levelLabel }}</span>
          </div>
          <div class="qt-prompt">{{ cur.prompt }}</div>
          <div class="qt-ctrl">
            <button class="qt-back" @click="back">← 退回</button>
            <button class="qt-next" @click="next">{{ nextLabel }}</button>
            <span class="qt-step">第 {{ stepNo }} / 3 步</span>
          </div>
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
        <div class="qt-score">
          <span class="qt-score-n" :style="{ color: scoreColor }">{{ cur.score }}</span>
          <span class="qt-score-u">/ 100 提问分</span>
        </div>
        <div class="qt-bar"><div class="qt-bar-f" :style="{ width: cur.score + '%', background: scoreColor }" /></div>
        <div class="qt-factors">
          <div v-for="f in factors" :key="f.key" :class="['qt-f', f.ok ? 'ok' : 'no']">
            <div class="qt-f-head">
              <span class="qt-f-icon">{{ f.ok ? '✓' : '○' }}</span>
              <span class="qt-f-name">{{ f.key }}</span>
              <span class="qt-f-desc">{{ f.desc }}</span>
            </div>
            <div class="qt-f-hint">{{ f.hint }}</div>
          </div>
        </div>
        <div class="qt-msg">{{ cur.msg }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.qt { max-width: 1040px; margin: 0 auto; }
.qt-header { margin-bottom: 18px; }
.qt-header h2 { font-family: var(--serif); font-size: 20px; font-weight: 600; color: var(--text); margin: 0 0 6px; }
.qt-header p { font-size: 14px; color: var(--muted); line-height: 1.7; margin: 0; max-width: 640px; }
.qt-grid { display: grid; grid-template-columns: 1fr 400px; gap: 18px; align-items: start; }
@media (max-width: 820px) { .qt-grid { grid-template-columns: 1fr; } }
.qt-left { display: flex; flex-direction: column; gap: 14px; }
.panel { background: var(--panel); border: 1px solid var(--border); border-radius: 13px; padding: 18px 20px; }

.qt-promptbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.qt-promptlabel { font-size: 13.5px; font-weight: 600; color: var(--text); }
.qt-lvl { font-size: 12px; color: var(--muted); }
.qt-prompt {
  background: #fff; border: 1px solid #e2dccd; border-radius: 11px; padding: 15px 16px; min-height: 130px;
  font-family: 'IBM Plex Mono', Consolas, monospace; font-size: 14.5px; line-height: 1.75; color: var(--text); white-space: pre-wrap;
}
.qt-ctrl { display: flex; align-items: center; gap: 10px; margin-top: 14px; }
.qt-back { font: inherit; font-size: 13px; font-weight: 600; color: var(--muted); background: #fff; border: 1px solid var(--border); border-radius: 9px; padding: 9px 16px; cursor: pointer; }
.qt-back:hover { color: var(--text); }
.qt-next { font: inherit; font-size: 13px; font-weight: 700; color: #fff; background: var(--primary); border: none; border-radius: 9px; padding: 9px 18px; cursor: pointer; }
.qt-step { font-size: 12.5px; color: var(--muted); margin-left: auto; }

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
.qt-score { display: flex; align-items: baseline; gap: 8px; margin-bottom: 6px; }
.qt-score-n { font-family: var(--serif); font-size: 38px; font-weight: 600; line-height: 1; }
.qt-score-u { font-size: 13px; color: var(--muted); }
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
.qt-f-hint { font-size: 12.5px; color: var(--muted); line-height: 1.55; margin-top: 6px; }
.qt-msg { margin-top: 16px; padding-top: 15px; border-top: 1px solid #f1e8da; font-size: 13.5px; line-height: 1.7; color: var(--text); }
</style>
