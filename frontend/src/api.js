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

export function getStudentId() {
  let id = localStorage.getItem('student_id')
  if (!id) {
    id = 'stu_' + Math.random().toString(36).slice(2, 8)
    localStorage.setItem('student_id', id)
  }
  return id
}

export const api = {
  listPatterns: () => request('GET', '/patterns'),
  createSession: (patternId) =>
    request('POST', '/sessions', { student_id: getStudentId(), pattern_id: patternId }),
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
  getRecommendations: () => request('GET', `/students/${getStudentId()}/recommendations`),
  getCapabilityEvents: (capability) =>
    request('GET', `/students/${getStudentId()}/capabilities/${capability}/events`),
}
