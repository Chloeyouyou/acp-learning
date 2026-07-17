<script setup>
defineProps({
  open: { type: Boolean, default: false },
  step: { type: Object, required: true },
  selectedLine: { type: Number, default: null },
  lineNote: { type: String, default: '' },
  walkLoading: { type: Boolean, default: false },
  visibleBricks: { type: Array, default: () => [] },
  hiddenBricks: { type: Array, default: () => [] },
  concepts: { type: Array, default: () => [] },
  askingTutor: { type: Boolean, default: false },
})

defineEmits([
  'toggle', 'clear-line', 'open-walk', 'change-route',
  'mark-brick', 'restore-brick', 'reset-bricks',
])
</script>

<template>
  <section class="learning-help">
    <button class="help-trigger" :class="{ open }" :aria-expanded="open" @click="$emit('toggle')">
      <span>
        <b>我卡住了</b>
        <small>{{ open ? '现在只看当前需要的帮助' : '逐行讲解、认符号、补概念都在这里' }}</small>
      </span>
      <span class="help-caret">{{ open ? '收起 ↑' : '打开 ↓' }}</span>
    </button>

    <div v-if="open" class="help-panel" aria-label="学习帮助">
      <div class="help-now">
        <span>现在只做这一步</span>
        <b>{{ step.name }}</b>
        <p>{{ step.goal }}</p>
      </div>

      <div v-if="selectedLine" class="line-focus">
        <div class="line-focus-head">
          <b>第 {{ selectedLine }} 行</b>
          <button @click="$emit('clear-line')">不再聚焦这行</button>
        </div>
        <p>{{ lineNote }}</p>
      </div>

      <div class="help-actions">
        <button class="help-action primary" :disabled="walkLoading" @click="$emit('open-walk')">
          {{ walkLoading ? '正在整理执行路线…' : '按执行顺序讲代码' }}
        </button>
        <button class="help-action" :disabled="askingTutor" @click="$emit('change-route')">
          {{ askingTutor ? '知返正在换一种讲法…' : '还是没懂，换一种讲法' }}
        </button>
      </div>

      <details v-if="visibleBricks.length || hiddenBricks.length" class="help-detail">
        <summary>认一个代码符号 <span v-if="visibleBricks.length">· {{ visibleBricks.length }} 个待认</span></summary>
        <div class="detail-body">
          <p v-if="!visibleBricks.length" class="detail-muted">这道题里的符号都被你标记为懂了。</p>
          <div v-for="brick in visibleBricks" :key="brick.name" class="syntax-item">
            <div class="syntax-row">
              <b>{{ brick.name }}</b>
              <button @click="$emit('mark-brick', brick.name)">✓ 懂了</button>
            </div>
            <span>{{ brick.desc }}</span>
          </div>
          <details v-if="hiddenBricks.length" class="hidden-bricks">
            <summary>已收起 {{ hiddenBricks.length }} 个懂了的符号</summary>
            <div v-for="brick in hiddenBricks" :key="brick.name" class="hidden-row">
              <b>{{ brick.name }}</b>
              <button @click="$emit('restore-brick', brick.name)">恢复</button>
            </div>
            <button class="reset-bricks" @click="$emit('reset-bricks')">全部恢复</button>
          </details>
        </div>
      </details>

      <details v-if="concepts.length" class="help-detail">
        <summary>补一个这道题用到的概念</summary>
        <div class="detail-body concept-list">
          <div v-for="concept in concepts" :key="concept.kp" class="concept-item">
            <div>
              <b>{{ concept.kp }}</b>
              <span :class="concept.mastered ? 'known' : 'new'">
                {{ concept.mastered ? '已掌握' : '当前需要' }}
              </span>
            </div>
            <p>{{ concept.desc || '遇到不懂的可以让知返换一种讲法。' }}</p>
          </div>
        </div>
      </details>
    </div>
  </section>
</template>

<style scoped>
.learning-help { display: flex; flex-direction: column; gap: 8px; }
.help-trigger {
  width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 18px;
  padding: 12px 15px; border: 1px solid #e7e2d6; border-radius: 11px;
  background: #fcfbf7; color: #6f695d; text-align: left; cursor: pointer; font: inherit;
}
.help-trigger:hover, .help-trigger.open { border-color: #d6b49d; background: #fbf5ed; }
.help-trigger > span:first-child { display: flex; flex-direction: column; gap: 2px; }
.help-trigger b { color: #2b2924; font-size: 14px; }
.help-trigger small { color: #8a8275; font-size: 12px; line-height: 1.45; }
.help-caret { color: #a54e30; font-size: 12px; white-space: nowrap; }
.help-panel { border: 1px solid #e7e2d6; border-radius: 11px; padding: 15px; background: #fcfbf7; }
.help-now { padding: 12px 14px; border-left: 3px solid #c15f3c; border-radius: 0 9px 9px 0; background: #f8efe5; }
.help-now > span { display: block; color: #8a8275; font-size: 11.5px; margin-bottom: 3px; }
.help-now > b { font-family: var(--serif); color: #2b2924; font-size: 16px; }
.help-now p { margin: 5px 0 0; color: #6f695d; font-size: 12.5px; line-height: 1.65; }
.line-focus { margin-top: 10px; padding: 11px 13px; border: 1px solid #eed7c8; border-radius: 9px; background: #fff; }
.line-focus-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.line-focus-head b { color: #a54e30; font-family: 'IBM Plex Mono', monospace; font-size: 12px; }
.line-focus-head button { border: 0; background: none; color: #8a8275; font: inherit; font-size: 11.5px; cursor: pointer; }
.line-focus p { margin: 7px 0 0; color: #3a3530; font-size: 13px; line-height: 1.7; }
.help-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 11px 0; }
.help-action { border: 1px solid #dcc5b4; border-radius: 9px; padding: 9px 11px; background: #fff; color: #6f695d; font: inherit; font-size: 12.5px; cursor: pointer; }
.help-action:hover { border-color: #c15f3c; color: #a54e30; }
.help-action.primary { background: #c15f3c; border-color: #c15f3c; color: #fff; }
.help-action:disabled { opacity: .55; cursor: wait; }
.help-detail { border-top: 1px solid #ece5d8; }
.help-detail > summary { list-style: none; cursor: pointer; padding: 11px 2px; color: #3a3530; font-size: 13px; font-weight: 600; }
.help-detail > summary::-webkit-details-marker { display: none; }
.help-detail > summary::after { content: '›'; float: right; color: #a54e30; }
.help-detail[open] > summary::after { transform: rotate(90deg); }
.help-detail summary span { color: #8a8275; font-weight: 400; }
.detail-body { display: flex; flex-direction: column; gap: 9px; padding: 0 2px 11px; }
.detail-muted { margin: 0; color: #8a8275; font-size: 12px; }
.syntax-item { display: flex; flex-direction: column; gap: 3px; }
.syntax-row, .hidden-row { display: flex; align-items: center; justify-content: space-between; gap: 9px; }
.syntax-row b, .hidden-row b { color: #a54e30; font-family: Consolas, monospace; font-size: 13px; }
.syntax-row button, .hidden-row button, .reset-bricks { border: 1px solid #e7e2d6; border-radius: 999px; background: #fff; color: #8a8275; font: inherit; font-size: 11px; cursor: pointer; }
.syntax-item > span { color: #6f695d; font-size: 12.5px; line-height: 1.55; }
.hidden-bricks { color: #8a8275; font-size: 12px; }
.hidden-bricks > summary { cursor: pointer; margin-bottom: 7px; }
.hidden-row { margin: 5px 0; }
.reset-bricks { margin-top: 4px; padding: 3px 9px; color: #a54e30; }
.concept-item { display: flex; flex-direction: column; gap: 4px; }
.concept-item > div { display: flex; align-items: center; gap: 8px; }
.concept-item b { font-family: var(--serif); color: #2b2924; font-size: 14px; }
.concept-item span { border-radius: 999px; padding: 1px 7px; font-size: 10.5px; }
.concept-item span.known { background: #e4ede0; color: #3f5837; }
.concept-item span.new { background: #f4e6d8; color: #a54e30; }
.concept-item p { margin: 0; color: #6f695d; font-size: 12.5px; line-height: 1.6; }
@media (max-width: 720px) { .help-actions { grid-template-columns: 1fr; } }
</style>
