<script setup>
import { computed } from 'vue'
import { LEARNING_STEPS, learningStepIndex } from '../learning-flow'

const props = defineProps({
  current: { type: String, required: true },
})

const currentIndex = computed(() => learningStepIndex(props.current))
</script>

<template>
  <ol class="stage-track" aria-label="学习四步">
    <li v-for="(step, index) in LEARNING_STEPS" :key="step.id"
        :class="{ done: index < currentIndex, active: index === currentIndex }">
      <span class="dot">{{ index < currentIndex ? '✓' : index + 1 }}</span>
      <span class="name">{{ step.name }}</span>
    </li>
  </ol>
</template>

<style scoped>
.stage-track { list-style: none; display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; margin: 12px 0 14px; padding: 0; }
.stage-track li { position: relative; display: flex; align-items: center; gap: 5px; min-width: 0; color: #aaa397; font-size: 11px; }
.stage-track li:not(:last-child)::after { content: ''; position: absolute; height: 1px; left: 24px; right: 1px; top: 10px; background: #ddd6ca; z-index: 0; }
.dot { position: relative; z-index: 1; flex: none; display: grid; place-items: center; width: 20px; height: 20px; border-radius: 50%; border: 1px solid #d8d0c3; background: #fcfbf7; font-size: 10px; }
.name { position: relative; z-index: 1; background: #fcfbf7; padding-right: 4px; white-space: nowrap; }
.stage-track li.done { color: #728363; }
.stage-track li.done .dot { border-color: #9bac8c; background: #edf2e8; }
.stage-track li.active { color: #7b5e42; font-weight: 700; }
.stage-track li.active .dot { color: #fff; border-color: #947654; background: #947654; box-shadow: 0 0 0 3px #eee4d6; }
@media (max-width: 720px) {
  .stage-track { grid-template-columns: repeat(2, 1fr); row-gap: 8px; }
  .stage-track li:nth-child(2)::after { display: none; }
}
</style>
