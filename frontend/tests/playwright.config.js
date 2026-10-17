import { defineConfig } from '@playwright/test'

const realStackE2E = process.env.REAL_STACK_E2E === '1'
const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:3000'

export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.js',
  timeout: 30000,
  retries: 0,
  webServer: realStackE2E ? undefined : {
    command: 'npm run dev -- --host 127.0.0.1 --strictPort',
    url: 'http://127.0.0.1:3000',
    reuseExistingServer: true,
    timeout: 120000,
  },
  use: {
    baseURL,
    headless: true,
    channel: 'chromium',  // 使用 playwright 自带 chromium（环境无系统 Chrome）
    screenshot: realStackE2E ? 'only-on-failure' : 'off',
    trace: realStackE2E ? 'retain-on-failure' : 'off',
    launchOptions: {
      args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
      timeout: 30000,
    },
  },
  reporter: [
    ['list'],
    ['json', { outputFile: 'test-results.json' }],
  ],
})
