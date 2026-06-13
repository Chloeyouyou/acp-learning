<script setup>
import { computed } from 'vue'
import { annotate } from '../glossary'

const props = defineProps({ text: { type: String, default: '' } })
const segments = computed(() => annotate(props.text))

// 悬停时若上方空间不足（提示会被滚动容器/视口裁切），就翻到下方弹出
function place(e) {
  const el = e.currentTarget
  el.classList.toggle('below', el.getBoundingClientRect().top < 140)
}
</script>

<template><span
  ><template v-for="(s, i) in segments" :key="i"
    ><span v-if="s.term" class="term" tabindex="0" @mouseenter="place" @focus="place"
      >{{ s.text }}<span class="term-pop">{{ s.term }}</span></span
    ><template v-else>{{ s.text }}</template
  ></template
></span></template>

<style scoped>
.term {
  position: relative;
  border-bottom: 1px dashed var(--primary);
  cursor: help;
  color: inherit;
}
.term-pop {
  position: absolute;
  left: 50%;
  bottom: calc(100% + 8px);
  transform: translateX(-50%);
  width: max-content;
  max-width: 260px;
  background: var(--text);
  color: #fff;
  font-size: 12.5px;
  line-height: 1.55;
  text-align: left;
  white-space: normal;
  padding: 8px 11px;
  border-radius: 8px;
  box-shadow: 0 8px 22px -8px rgba(0, 0, 0, 0.45);
  opacity: 0;
  visibility: hidden;
  transition: opacity 0.14s ease;
  z-index: 50;
  pointer-events: none;
}
.term-pop::after {
  content: '';
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 5px solid transparent;
  border-top-color: var(--text);
}
/* 上方空间不足时翻到下方 */
.term.below .term-pop {
  bottom: auto;
  top: calc(100% + 8px);
}
.term.below .term-pop::after {
  top: auto;
  bottom: 100%;
  border-top-color: transparent;
  border-bottom-color: var(--text);
}
.term:hover .term-pop,
.term:focus .term-pop {
  opacity: 1;
  visibility: visible;
}
</style>
