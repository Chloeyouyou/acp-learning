const EYEBROW = {
  resume: '先收尾',
  review: '趁热巩固',
  recommend: '补一块能力',
  start: '开始积累',
}

export function nextActionEyebrow(guidance) {
  return EYEBROW[guidance?.action?.kind] || EYEBROW.start
}

export function nextActionTarget(guidance) {
  const action = guidance?.action
  if (action?.kind === 'resume' && action.target?.session_id) {
    return { path: '/arena', query: { resume: action.target.session_id } }
  }
  if (action?.target?.pattern_id) {
    return {
      path: '/arena',
      query: {
        start: action.target.pattern_id,
        ...(action.target.mode === 'review' ? { mode: 'review' } : {}),
      },
    }
  }
  return { path: '/arena' }
}

export function nextActionQueueHint(guidance) {
  const kind = guidance?.action?.kind
  const pending = guidance?.pending || {}
  if (kind === 'resume' && pending.reviews) {
    return `完成后，还有 ${pending.reviews} 道到期复习会接着排进来。`
  }
  if (kind === 'review' && pending.reviews > 1) {
    return `先做这一道，其余 ${pending.reviews - 1} 道稍后再来。`
  }
  return ''
}
