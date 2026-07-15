<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const router = useRouter()
const units = ref([])
const error = ref('')
const loading = ref(true)

const STATE = {
  未接触: { cls: 'new', icon: '', label: '未开始' },
  已接触: { cls: 'touched', icon: '·', label: '进行中' },
  已解决: { cls: 'solved', icon: '✓', label: '已解决' },
  已内化: { cls: 'mastered', icon: '★', label: '已内化' },
}

onMounted(async () => {
  try {
    const r = await api.getCurriculum()
    units.value = r.units || []
  } catch (e) {
    error.value = '加载失败：' + e.message
  } finally {
    loading.value = false
  }
})

function startLevel(pid) {
  router.push({ path: '/arena', query: { start: pid } })
}
function st(level) { return STATE[level.state] || STATE['未接触'] }
</script>

<template>
  <div class="map">
    <header class="head">
      <h1>学习地图</h1>
      <p class="sub">想自己选时再来这里。按主题顺着练，或挑一个现在最想弄懂的问题。</p>
    </header>

    <div v-if="loading" class="hint">加载中…</div>
    <div v-else-if="error" class="hint err">{{ error }}</div>

    <div v-else class="units">
      <section v-for="u in units" :key="u.id" class="unit">
        <div class="unit-head">
          <div class="unit-title">
            <span class="unit-id">{{ u.id }}</span>
            <h2>{{ u.name }}</h2>
          </div>
          <div class="unit-progress">
            <span>{{ u.solved }}/{{ u.total }} 已解决<template v-if="u.internalized"> · {{ u.internalized }} 已内化</template></span>
            <div class="bar"><div class="fill" :style="{ width: (u.total ? u.solved / u.total * 100 : 0) + '%' }"></div></div>
          </div>
        </div>
        <p class="unit-desc">{{ u.description }}</p>

        <div class="levels">
          <button v-for="(lv, i) in u.levels" :key="lv.pattern_id"
                  :class="['level', st(lv).cls, { due: lv.due }]"
                  @click="startLevel(lv.pattern_id)"
                  :title="lv.name">
            <span class="lv-num">{{ i + 1 }}</span>
            <span class="lv-name">{{ lv.name }}</span>
            <span class="lv-foot">
              <span class="diff">{{ lv.difficulty }}</span>
              <span v-if="st(lv).icon" class="badge">{{ st(lv).icon }}</span>
              <span v-if="lv.due" class="review" title="到复习期了">🔁</span>
            </span>
          </button>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.map { max-width: 820px; margin: 0 auto; padding: 20px 16px 60px; }
.head h1 { font-family: var(--serif); font-size: 24px; color: var(--text); margin: 0 0 8px; }
.sub { font-size: 13.5px; color: var(--muted); line-height: 1.7; margin: 0 0 8px; }
.hint { text-align: center; color: var(--muted); margin: 60px 0; }
.hint.err { color: var(--red); }

.units { display: flex; flex-direction: column; gap: 20px; margin-top: 22px; }
.unit { background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 18px 18px 20px; }
.unit-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 14px; flex-wrap: wrap; }
.unit-title { display: flex; align-items: baseline; gap: 9px; }
.unit-id { font-size: 12px; font-weight: 700; color: var(--primary); }
.unit-title h2 { font-family: var(--serif); font-size: 18px; color: var(--text); margin: 0; }
.unit-progress { font-size: 12px; color: var(--muted); text-align: right; }
.bar { width: 130px; height: 5px; background: var(--border); border-radius: 999px; margin-top: 5px; overflow: hidden; }
.fill { height: 100%; background: var(--green); border-radius: 999px; transition: width .3s; }
.unit-desc { font-size: 13px; color: var(--muted); line-height: 1.6; margin: 10px 0 14px; }

.levels { display: flex; flex-wrap: wrap; gap: 10px; }
.level {
  width: 148px; text-align: left; background: var(--bg); border: 1px solid var(--border);
  border-radius: 10px; padding: 10px 11px; cursor: pointer; font-family: inherit;
  display: flex; flex-direction: column; gap: 6px; transition: border-color .15s, transform .1s;
}
.level:hover { border-color: var(--primary); transform: translateY(-1px); }
.lv-num { font-size: 11px; color: var(--muted); }
.lv-name { font-size: 13px; color: var(--text); line-height: 1.4; min-height: 36px; }
.lv-foot { display: flex; align-items: center; gap: 6px; }
.diff { font-size: 10.5px; color: var(--muted); background: var(--accent-soft); border-radius: 4px; padding: 1px 5px; }
.badge { margin-left: auto; font-size: 13px; }
.review { font-size: 12px; }

/* 状态色 */
.level.solved { border-color: #cfe0c4; }
.level.solved .badge { color: var(--green); }
.level.mastered { border-color: var(--green); background: #f2f6ee; }
.level.mastered .badge { color: var(--green); }
.level.touched .badge { color: var(--primary); }
.level.due { border-color: #e0c9a8; }

@media (max-width: 640px) {
  .level { width: calc(50% - 5px); }
}
</style>
