<script setup>
import { computed } from 'vue'

const props = defineProps({
  sessionId: { type: String, required: true },
  variant: { type: Object, default: null },
  action: { type: Object, default: null },
  loading: { type: Boolean, default: false },
})

defineEmits(['continue'])

const title = computed(() => props.variant
  ? `用“${props.variant.name}”检验是否真的会迁移`
  : (props.action?.title || '继续下一步学习'))
const detail = computed(() => props.variant
  ? '这次已经想通了，再独立处理一道同类问题，才能知道方法有没有真正带走。'
  : (props.action?.detail || '系统正在整理最适合接着做的一步。'))
const cta = computed(() => props.variant ? '检验能否迁移' : (props.action?.cta || '继续学习'))
</script>

<template>
  <section class="completion-panel" aria-label="完成后的下一步">
    <span class="completion-kicker">这次已完成</span>
    <b>你不只修好了，也把它讲清楚了。</b>
    <div class="next-block">
      <span>只做下一步</span>
      <strong>{{ title }}</strong>
      <p>{{ detail }}</p>
      <button :disabled="loading" @click="$emit('continue')">
        {{ loading ? '正在整理…' : `${cta} →` }}
      </button>
    </div>
    <RouterLink :to="`/replay/${sessionId}`">安静回看这次是怎么想通的</RouterLink>
  </section>
</template>

<style scoped>
.completion-panel { padding: 15px 17px; border: 1px solid #b8ceb0; border-radius: 11px; background: #f3f8ef; color: #355133; }
.completion-kicker { display: block; margin-bottom: 4px; color: #688064; font-size: 11.5px; }
.completion-panel > b { font-family: var(--serif); font-size: 15px; }
.next-block { margin-top: 12px; padding-top: 11px; border-top: 1px solid #d4e1cf; }
.next-block > span { display: block; color: #688064; font-size: 11px; margin-bottom: 3px; }
.next-block strong { display: block; color: #2f482d; font-size: 14px; line-height: 1.45; }
.next-block p { margin: 5px 0 9px; color: #5c7058; font-size: 12px; line-height: 1.6; }
.next-block button { border: 0; border-radius: 8px; padding: 8px 13px; background: #688064; color: #fff; font: inherit; font-size: 12.5px; cursor: pointer; }
.next-block button:disabled { opacity: .55; cursor: wait; }
.completion-panel > a { display: inline-block; margin-top: 10px; color: #688064; font-size: 11.5px; text-decoration: none; }
.completion-panel > a:hover { text-decoration: underline; }
</style>
