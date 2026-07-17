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
  await expect(page.locator('details.more-nav summary')).toHaveText('专项练习')
  await page.locator('details.more-nav summary').click()
  await expect(page.getByRole('link', { name: 'AI 共脑调试' })).toBeVisible()
  await expect(page.getByRole('link', { name: '提问训练' })).toBeVisible()
  await expect(page.getByRole('link', { name: '能力画像' })).toHaveCount(0)

  const lobbyAction = page.locator('button.smart-open.hero')
  await expect(lobbyAction).toHaveCount(1)
  await expect(lobbyAction).toContainText('按推荐练习')
  await lobbyAction.click()
  await expect(page.getByRole('heading', { name: '当前任务' })).toBeVisible()
  const learningSteps = page.getByLabel('学习四步')
  await expect(learningSteps.locator('li')).toHaveCount(4)
  await expect(learningSteps).toContainText('运行观察')
  await expect(learningSteps).toContainText('定位原因')
  await expect(learningSteps).toContainText('修改验证')
  await expect(learningSteps).toContainText('总结迁移')
  const helpButton = page.getByRole('button', { name: /我卡住了/ })
  await expect(helpButton).toHaveCount(1)
  await helpButton.click()
  await expect(page.getByLabel('学习帮助')).toContainText('现在只做这一步')
  await helpButton.click()
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
  const mainline = page.getByLabel('主线回放').locator('.step')
  const mainlineCount = await mainline.count()
  expect(mainlineCount).toBeGreaterThan(0)
  await expect(page.getByText('真实动作').first()).toBeVisible()
  await page.getByText('查看技术凭据').first().click()
  await expect(page.getByText(/风险 L[12]/).first()).toBeVisible()
  await page.getByRole('button', { name: /查看完整过程/ }).click()
  const fullProcess = page.getByLabel('完整过程').locator('.step')
  expect(await fullProcess.count()).toBeGreaterThan(mainlineCount)
  await page.getByRole('button', { name: '只看主线' }).click()
  await expect(page.getByLabel('主线回放')).toBeVisible()

  await page.goto('/timeline')
  await expect(page.getByRole('heading', { name: '每一次想通，都有证据' })).toBeVisible()
  await expect(page.getByLabel('成长证据链')).toContainText('真实动作')
  await expect(page.getByLabel('成长证据链')).toContainText('关键转折')
  await expect(page.getByLabel('成长证据链')).toContainText('内化经验')
  await expect(page.getByLabel('唯一下一步').locator('.next-action')).toHaveCount(1)
  await expect(page.getByLabel('唯一下一步')).toContainText('继续想通')

  const guidanceResponse = await request.get(`/api/students/${studentId}/next-action`, { headers })
  expect(guidanceResponse.ok()).toBeTruthy()
  const guidance = await guidanceResponse.json()
  expect(guidance.action.kind).toBe('resume')
  expect(guidance.action.reason_code).toBe('unfinished_first')

  await page.goto('/arena')
  await expect(page.locator('button.smart-open.hero')).toContainText(guidance.action.title)
  await page.goto('/map')
  await expect(page.getByLabel('按证据推荐')).toBeVisible()
  await expect(page.getByLabel('按证据推荐').locator('.recommend-card')).not.toHaveCount(0)
  await page.goto('/profile?tab=推荐')
  await expect(page.getByRole('button', { name: '推荐与题库' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: /去学习地图选题/ })).toBeVisible()

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
