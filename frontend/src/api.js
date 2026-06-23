const BASE = '/api'

async function request(method, path, body) {
  const res = await fetch(BASE + path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error(detail.detail || `请求失败 (${res.status})`)
  }
  return res.json()
}

// ---- 轻量身份（无密码/无后端鉴权）：学号即稳定 student_id，存 localStorage ----
// 解决旧的随机 student_id 一清缓存/换设备就丢进度的问题。
const ID_KEY = 'student_id'
const NAME_KEY = 'student_name'
const CHOSEN_KEY = 'identity_chosen'  // '1' = 用户已显式确认过身份（区分旧的随机 id）

export function getStudentId() {
  return localStorage.getItem(ID_KEY) || ''
}

export function getStudentName() {
  return localStorage.getItem(NAME_KEY) || ''
}

// 是否已确立身份（已显式选过 + 有 id）。否则 App 弹身份页。
export function hasIdentity() {
  return localStorage.getItem(CHOSEN_KEY) === '1' && !!getStudentId()
}

// 本设备遗留的旧随机 id（有 id 但没显式选过身份）——用于迁移提示；新访客返回 ''
export function getLegacyId() {
  if (localStorage.getItem(CHOSEN_KEY) === '1') return ''
  return getStudentId()
}

// 用学号（+可选姓名）确立身份
export function setIdentity(id, name = '') {
  localStorage.setItem(ID_KEY, id)
  if (name) localStorage.setItem(NAME_KEY, name)
  else localStorage.removeItem(NAME_KEY)
  localStorage.setItem(CHOSEN_KEY, '1')
}

// 沿用本设备已有记录（旧随机 id）：保留 id，仅标记为已选 + 可补姓名
export function keepLegacyIdentity(name = '') {
  if (name) localStorage.setItem(NAME_KEY, name)
  localStorage.setItem(CHOSEN_KEY, '1')
}

// 切换身份：撤销「已选」标记，重新进入身份页（不删旧 id，仍作迁移候选）
export function clearIdentityChoice() {
  localStorage.removeItem(CHOSEN_KEY)
}

export const api = {
  listPatterns: () => request('GET', '/patterns'),
  createSession: (patternId, mode = 'debug') =>
    request('POST', '/sessions', { student_id: getStudentId(), pattern_id: patternId, mode }),
  sendMessage: (sessionId, content) =>
    request('POST', `/sessions/${sessionId}/messages`, { content }),
  submitFix: (sessionId, code) =>
    request('POST', `/sessions/${sessionId}/submit`, { code }),
  runCode: (sessionId, code) =>
    request('POST', `/sessions/${sessionId}/run`, { code }),
  getSession: (sessionId) => request('GET', `/sessions/${sessionId}`),
  getWalkthrough: (patternId, deep = false) =>
    request('GET', `/patterns/${patternId}/walkthrough${deep ? '?deep=true' : ''}`),
  getProfile: () => request('GET', `/students/${getStudentId()}/profile`),
  getTimeline: () => request('GET', `/students/${getStudentId()}/timeline`),
  getReviewQueue: () => request('GET', `/students/${getStudentId()}/review-queue`),
  getActiveSessions: () => request('GET', `/students/${getStudentId()}/active-sessions`),
  abandonSession: (sessionId) => request('POST', `/sessions/${sessionId}/abandon`),
  getRecommendations: () => request('GET', `/students/${getStudentId()}/recommendations`),
  getCapabilityEvents: (capability) =>
    request('GET', `/students/${getStudentId()}/capabilities/${capability}/events`),
  diagnoseQuestion: (scenarioId, prompt) =>
    request('POST', '/question-training/diagnose', { scenario_id: scenarioId, prompt, student_id: getStudentId() }),
  getQuestionWeakness: () =>
    request('GET', `/students/${getStudentId()}/question-training/weakness`),
  // AI 共脑调试（结对调试）
  coopSamples: () => request('GET', '/coop/samples'),
  coopStart: (sampleId) =>
    request('POST', '/coop/start', { student_id: getStudentId(), sample_id: sampleId }),
  coopGet: (sessionId) => request('GET', `/coop/${sessionId}`),
  coopRun: (sessionId, code) => request('POST', `/coop/${sessionId}/run`, { code }),
  coopMessage: (sessionId, content) => request('POST', `/coop/${sessionId}/message`, { content }),
  coopResolve: (sessionId) => request('POST', `/coop/${sessionId}/resolve`),
}
