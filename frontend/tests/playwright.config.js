import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.js',
  timeout: 30000,
  retries: 0,
  use: {
    baseURL: 'http://localhost:3000',
    headless: true,
    channel: 'chrome',
    // 禁止截图 — 部分 AI 模型无法处理图片，用文本断言代替
    screenshot: 'off',
    trace: 'off',
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
