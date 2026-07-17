<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const router = useRouter()
const units = ref([])
const recommendations = ref([])
const error = ref('')
const loading = ref(true)

const STATE = {
  未接触: { cls: 'new', icon: '', label: '未开始' },
  已接触: { cls: 'touched', icon: '·', label: '进行中' },
  已解决: { cls: 'solved', icon: '✓', label: '已解决' },
  已内化: { cls: 'mastered', icon: '★', label: '已内化' },
}

onMounted(async () => {
  const [curriculum, recs] = await Promise.allSettled([
    api.getCurriculum(), api.getRecommendations(),
  ])
  if (curriculum.status === 'fulfilled') units.value = curriculum.value.units || []
  else error.value = '加载失败：' + curriculum.reason.message
  if (recs.status === 'fulfilled') recommendations.value = recs.value || []
  loading.value = false
})

function startLevel(pid, mode = 'debug') {
  router.push({ path: '/arena', query: { start: pid, ...(mode === 'review' ? { mode: 'review' } : {}) } })
}
function startRecommendation(rec) { startLevel(rec.id, rec.state === '已解决' ? 'review' : 'debug') }
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

    <template v-else>
      <section v-if="recommendations.length" class="recommendations" aria-label="按证据推荐">
        <div class="recommend-head">
          <div>
            <span class="recommend-eyebrow">按证据推荐</span>
            <h2>现在值得练的几道题</h2>
          </div>
          <span class="recommend-note">建议，不是必做</span>
        </div>
        <div class="recommend-grid">
          <button v-for="rec in recommendations" :key="rec.id" class="recommend-card" @click="startRecommendation(rec)">
            <span class="recommend-reason">{{ rec.reason }}</span>
            <strong>{{ rec.name }}</strong>
            <span class="recommend-meta">{{ rec.difficulty }}<template v-if="rec.knowledge_points?.length"> · {{ rec.knowledge_points.join('、') }}</template></span>
            <span class="recommend-go">{{ rec.state === '已解决' ? '开始复习' : '开始练习' }} →</span>
          </button>
        </div>
      </section>

      <div class="path-head">
        <h2>全部学习路径</h2>
        <span>按主题查看所有关卡</span>
      </div>
      <div class="units">
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
    </template>
  </div>
</template>

<style scoped>
.map { max-width: 820px; margin: 0 auto; padding: 20px 16px 60px; }
.head h1 { font-family: var(--serif); font-size: 24px; color: var(--text); margin: 0 0 8px; }
.sub { font-size: 13.5px; color: var(--muted); line-height: 1.7; margin: 0 0 8px; }
.hint { text-align: center; color: var(--muted); margin: 60px 0; }
.hint.err { color: var(--red); }
.recommendations { margin-top: 22px; padding: 17px; border: 1px solid #dcc5b4; border-radius: 14px; background: #fbf6ef; }
.recommend-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.recommend-eyebrow { color: var(--primary); font-size: 11px; font-weight: 700; letter-spacing: .1em; }
.recommend-head h2, .path-head h2 { margin: 5px 0 0; font-family: var(--serif); font-size: 18px; }
.recommend-note, .path-head span { color: var(--muted); font-size: 11.5px; }
.recommend-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px; margin-top: 13px; }
.recommend-card { display: flex; flex-direction: column; gap: 4px; text-align: left; padding: 12px 13px; border: 1px solid var(--border); border-radius: 10px; background: var(--panel); cursor: pointer; font: inherit; }
.recommend-card:hover { border-color: var(--primary); }
.recommend-reason { color: var(--primary-dark); font-size: 11.5px; }
.recommend-card strong { color: var(--text); font-family: var(--serif); font-size: 14.5px; }
.recommend-meta { color: var(--muted); font-size: 11.5px; line-height: 1.45; }
.recommend-go { margin-top: 3px; color: var(--primary); font-size: 12px; }
.path-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-top: 24px; }

.units { display: flex; flex-direction: column; gap: 20px; margin-top: 10px; }
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
