import { expect, test } from '@playwright/test'

const PATTERN_ID = 'BP-BOUNDARY-001'

test('学生可以从身份页进入并获得有效身份', async ({ page }) => {
  const studentId = `e2e_ui_${Date.now()}`
  await page.goto('/')

  await expect(page.getByRole('heading', { name: '从这里继续你的学习' })).toBeVisible()
  await expect(page.getByText('陪你想通，不替你写完。')).toBeVisible()
  await page.getByLabel('学号').fill(studentId)
  await page.getByLabel(/姓名/).fill('端到端同学')
  await page.getByRole('button', { name: '进入' }).click()

  await expect(page.getByTitle('切换身份')).toContainText('端到端同学')
  await expect.poll(() => page.evaluate(() => localStorage.getItem('student_id'))).toBe(studentId)
  await expect(page).toHaveURL(/\/arena$/)
  await expect(page.getByRole('heading', { name: '今天，自己想通一个问题' })).toBeVisible()

  const primaryNav = page.locator('header.topbar nav > a')
  await expect(primaryNav).toHaveCount(3)
  await expect(primaryNav).toHaveText(['开始练习', '学习地图', '我的成长'])
  await page.locator('details.more-nav summary').click()
  await expect(page.getByRole('link', { name: 'AI 共脑调试' })).toBeVisible()
  await expect(page.getByRole('link', { name: '提问训练' })).toBeVisible()
  await expect(page.getByRole('link', { name: '能力画像' })).toBeVisible()

  await page.getByRole('button', { name: /开始一次调试/ }).click()
  await expect(page.getByRole('heading', { name: '当前任务' })).toBeVisible()
  await expect(page.locator('.thought-step:visible')).toHaveCount(1)
  await page.getByRole('button', { name: '查看完整记录' }).click()
  await expect(page.locator('.thought-step:visible')).toHaveCount(4)
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
  await expect(page.getByText('真实动作').first()).toBeVisible()
  await page.getByText('查看技术凭据').first().click()
  await expect(page.getByText(/风险 L[12]/).first()).toBeVisible()

  await page.goto('/timeline')
  await expect(page.getByRole('heading', { name: '每一次想通，都有证据' })).toBeVisible()
  await expect(page.getByLabel('成长证据链')).toContainText('真实动作')
  await expect(page.getByLabel('成长证据链')).toContainText('关键转折')
  await expect(page.getByLabel('成长证据链')).toContainText('内化经验')

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
