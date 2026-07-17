import { defineConfig } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const python = process.env.E2E_PYTHON || 'python'
const quote = (value) => /\s/.test(value) ? `"${value}"` : value

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ['line'],
    ['html', { open: 'never', outputFolder: 'playwright-report' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:8000',
    browserName: 'chromium',
    ...(process.env.CI ? {} : { channel: 'chrome' }),
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    viewport: { width: 1365, height: 900 },
  },
  webServer: {
    command: `${quote(python)} -m uvicorn app.main:app --host 127.0.0.1 --port 8000`,
    cwd: path.resolve(here, '../backend'),
    url: 'http://127.0.0.1:8000/api/health',
    // CI 自己拉起并回收服务；本地调试可先起服务再设 PW_REUSE_SERVER=1，避免 Windows 子进程回收差异。
    reuseExistingServer: process.env.PW_REUSE_SERVER === '1',
    timeout: 120_000,
    stdout: 'pipe',
    stderr: 'pipe',
    env: {
      ...process.env,
      DATABASE_URL: process.env.E2E_DATABASE_URL || 'sqlite:///./acp-e2e.db',
      ACP_ENV: 'development',
      ACP_SANDBOX: 'subprocess',
      ACP_ADMIN_TOKEN: 'e2e-admin-token',
      ACP_AUTH_SECRET: 'e2e-auth-secret-at-least-32-bytes',
      DEEPSEEK_API_KEY: 'e2e-not-used',
    },
  },
})
