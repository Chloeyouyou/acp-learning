<script setup>
import { computed } from 'vue'

// dimensions: [{name, score (0-100|null), confidence: 'low'|'normal'}]
const props = defineProps({ dimensions: { type: Array, required: true } })

const SIZE = 280
const CX = SIZE / 2
const CY = SIZE / 2
const R = 100

const axes = computed(() =>
  props.dimensions.map((d, i) => {
    const angle = (Math.PI * 2 * i) / props.dimensions.length - Math.PI / 2
    return {
      ...d,
      x: CX + R * Math.cos(angle),
      y: CY + R * Math.sin(angle),
      lx: CX + (R + 24) * Math.cos(angle),
      ly: CY + (R + 24) * Math.sin(angle),
      angle,
    }
  })
)

const rings = [0.25, 0.5, 0.75, 1].map((f) => f * R)

function ringPoints(r) {
  return axes.value
    .map((a) => `${CX + r * Math.cos(a.angle)},${CY + r * Math.sin(a.angle)}`)
    .join(' ')
}

const valuePoints = computed(() =>
  axes.value
    .map((a) => {
      const score = a.score ?? 0
      const r = (score / 100) * R
      return `${CX + r * Math.cos(a.angle)},${CY + r * Math.sin(a.angle)}`
    })
    .join(' ')
)
</script>

<template>
  <svg :viewBox="`0 0 ${SIZE} ${SIZE}`" class="radar">
    <polygon v-for="r in rings" :key="r" :points="ringPoints(r)" class="ring" />
    <line v-for="a in axes" :key="a.name" :x1="CX" :y1="CY" :x2="a.x" :y2="a.y" class="axis" />
    <polygon :points="valuePoints" class="value" />
    <g v-for="a in axes" :key="'l' + a.name">
      <text :x="a.lx" :y="a.ly" text-anchor="middle" class="label">{{ a.name }}</text>
      <text :x="a.lx" :y="a.ly + 14" text-anchor="middle" class="score" :class="{ low: a.confidence === 'low' }">
        {{ a.score == null ? '未评估' : a.score }}
      </text>
    </g>
  </svg>
</template>

<style scoped>
.radar { width: 100%; max-width: 360px; }
.ring { fill: none; stroke: var(--border); }
.axis { stroke: var(--border); }
.value { fill: rgba(37, 99, 235, 0.25); stroke: var(--primary); stroke-width: 2; }
.label { font-size: 12px; fill: var(--text); font-weight: 600; }
.score { font-size: 11px; fill: var(--primary); }
.score.low { fill: var(--muted); }
</style>
