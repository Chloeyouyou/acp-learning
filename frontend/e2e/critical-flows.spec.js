import { expect, test } from '@playwright/test'

const PATTERN_ID = 'BP-BOUNDARY-001'

test('学生可以从身份页进入并获得有效身份', async ({ page }) => {
  const studentId = `e2e_ui_${Date.now()}`
  await page.goto('/')

  await expect(page.getByRole('heading', { name: '先填一下你的身份' })).toBeVisible()
  await page.getByLabel('学号').fill(studentId)
  await page.getByLabel(/姓名/).fill('端到端同学')
  await page.getByRole('button', { name: '进入' }).click()

  await expect(page.getByTitle('切换身份')).toContainText(studentId)
  await expect(page).toHaveURL(/\/arena$/)
})

test('运行提交后，学生回放与教师钻取共享同一条证据链', async ({ page, request }) => {
  const studentId = `e2e_flow_${Date.now()}`
  const login = await request.post('/api/auth/login', {
    data: { student_id: studentId, name: '证据链同学' },
  })
  expect(login.ok()).toBeTruthy()
  const { token } = await login.json()
  const headers = { Authorization: `Bearer ${token}` }

  const created = await request.post('/api/sessions', {
    headers,
    data: { pattern_id: PATTERN_ID, mode: 'debug' },
  })
  expect(created.ok()).toBeTruthy()
  const session = await created.json()

  const run = await request.post(`/api/sessions/${session.session_id}/run`, {
    headers,
    data: { code: session.code },
  })
  expect(run.ok()).toBeTruthy()
  expect((await run.json()).stderr).toContain('IndexError')

  const fixedCode = session.code.replace('range(len(arr) + 1)', 'range(len(arr))')
  const submitted = await request.post(`/api/sessions/${session.session_id}/submit`, {
    headers,
    data: { code: fixedCode },
  })
  expect(submitted.ok()).toBeTruthy()
  expect((await submitted.json()).passed).toBe(true)

  await page.addInitScript(({ id, authToken }) => {
    localStorage.setItem('student_id', id)
    localStorage.setItem('student_name', '证据链同学')
    localStorage.setItem('auth_token', authToken)
    localStorage.setItem('identity_chosen', '1')
    sessionStorage.setItem('acp_teacher_token', 'e2e-admin-token')
  }, { id: studentId, authToken: token })

  await page.goto(`/replay/${session.session_id}`)
  await expect(page.getByText('这里出现了关键突破').first()).toBeVisible()
  await expect(page.getByText('动作证据').first()).toBeVisible()
  await expect(page.getByText(/风险 L[12]/).first()).toBeVisible()

  await page.goto('/teacher')
  await expect(page.getByRole('heading', { name: '教师总览' })).toBeVisible()
  const row = page.locator('tr.student-row').filter({ hasText: studentId })
  await expect(row).toBeVisible()
  await row.click()
  await expect(page.getByText('学生钻取')).toBeVisible()
  await expect(page.getByText('两轮恢复率')).toBeVisible()

  await page.getByRole('button', { name: /查看过程回放/ }).first().click()
  await expect(page).toHaveURL(new RegExp(`/teacher/replay/${session.session_id}$`))
  await expect(page.getByText('这里出现了关键突破').first()).toBeVisible()
})
