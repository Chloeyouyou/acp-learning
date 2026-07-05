const BASE = '/api'

async function request(method, path, body) {
  const headers = {}
  if (body) headers['Content-Type'] = 'application/json'
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(BASE + path, {
    method,
    headers: Object.keys(headers).length ? headers : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    // token 失效/未登录：撤销身份选择，让 App 弹回身份页重新登录（不直接 reload，交给调用方）
    if (res.status === 401) {
      clearIdentityChoice()
      throw new Error('登录已失效，请重新输入学号进入')
    }
    const detail = await res.json().catch(() => ({}))
    throw new Error(detail.detail || `请求失败 (${res.status})`)
  }
  return res.json()
}

// ---- 轻量身份（无密码）：学号即稳定 student_id；登录换一个 HMAC 签名 token 存本地，----
// 之后每次请求带 token，服务端据此鉴权（挡改 URL 看别人数据）。学号是稳定身份——
// 换设备/清缓存后输同一学号即找回全部进度。
const ID_KEY = 'student_id'
const NAME_KEY = 'student_name'
const TOKEN_KEY = 'auth_token'
const CHOSEN_KEY = 'identity_chosen'  // '1' = 用户已显式确认过身份（区分旧的随机 id）

export function getStudentId() {
  return localStorage.getItem(ID_KEY) || ''
}

export function getStudentName() {
  return localStorage.getItem(NAME_KEY) || ''
}

function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

// 是否已确立身份（已显式选过 + 有 id + 有 token）。否则 App 弹身份页。
export function hasIdentity() {
  return localStorage.getItem(CHOSEN_KEY) === '1' && !!getStudentId() && !!getToken()
}

// 本设备遗留的旧随机 id（有 id 但没显式选过身份）——用于迁移提示；新访客返回 ''
export function getLegacyId() {
  if (localStorage.getItem(CHOSEN_KEY) === '1') return ''
  return getStudentId()
}

// 向后端登录：拿学号换 token 并落地本地身份。所有确立身份的入口都走它，保证 token 与 id 一致
// （老「登录后记录没了」的根因是 id 前后对不上——统一走 login 签发后不再发生）。
async function login(id, name = '') {
  const out = await request('POST', '/auth/login', { student_id: id, name })
  localStorage.setItem(ID_KEY, out.student_id)
  localStorage.setItem(TOKEN_KEY, out.token)
  if (name) localStorage.setItem(NAME_KEY, name)
  else localStorage.removeItem(NAME_KEY)
  localStorage.setItem(CHOSEN_KEY, '1')
  return out
}

// 用学号（+可选姓名）确立身份：登录签发 token。异步——调用方需 await。
export async function setIdentity(id, name = '') {
  return login(id, name)
}

// 沿用本设备已有记录（旧随机 id）：用该 id 登录换 token，保留原进度。异步。
export async function keepLegacyIdentity(name = '') {
  const legacy = getStudentId()
  if (!legacy) throw new Error('本设备无可沿用的记录')
  return login(legacy, name)
}

// 切换身份：撤销「已选」标记 + 清 token，重新进入身份页（不删旧 id，仍作迁移候选）
export function clearIdentityChoice() {
  localStorage.removeItem(CHOSEN_KEY)
  localStorage.removeItem(TOKEN_KEY)
}

export const api = {
  listPatterns: () => request('GET', '/patterns'),
  createSession: (patternId, mode = 'debug') =>
    request('POST', '/sessions', { pattern_id: patternId, mode }),
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
  getPresence: () => request('GET', `/students/${getStudentId()}/presence`),
  getTimeline: () => request('GET', `/students/${getStudentId()}/timeline`),
  getReviewQueue: () => request('GET', `/students/${getStudentId()}/review-queue`),
  getActiveSessions: () => request('GET', `/students/${getStudentId()}/active-sessions`),
  abandonSession: (sessionId) => request('POST', `/sessions/${sessionId}/abandon`),
  getRecommendations: () => request('GET', `/students/${getStudentId()}/recommendations`),
  getCapabilityEvents: (capability) =>
    request('GET', `/students/${getStudentId()}/capabilities/${capability}/events`),
  diagnoseQuestion: (scenarioId, prompt) =>
    request('POST', '/question-training/diagnose', { scenario_id: scenarioId, prompt }),
  getQuestionWeakness: () =>
    request('GET', `/students/${getStudentId()}/question-training/weakness`),
  // AI 共脑调试（结对调试）
  coopSamples: () => request('GET', '/coop/samples'),
  coopStart: (sampleId) =>
    request('POST', '/coop/start', { sample_id: sampleId }),
  coopStartCustom: (code, problem) =>
    request('POST', '/coop/start-custom', { code, problem }),
  coopGet: (sessionId) => request('GET', `/coop/${sessionId}`),
  coopRun: (sessionId, code) => request('POST', `/coop/${sessionId}/run`, { code }),
  coopMessage: (sessionId, content) => request('POST', `/coop/${sessionId}/message`, { content }),
  coopResolve: (sessionId) => request('POST', `/coop/${sessionId}/resolve`),
  coopWalkthrough: (code, deep = false) => request('POST', '/coop/walkthrough', { code, deep }),
}
