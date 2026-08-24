import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const runsPayload = {
  runs: [
    {
      id: 21,
      comparison_group: 'release-ab-2026-08',
      target_release_key: 'interview-agent@1.0',
      status: 'completed',
      items: [],
    },
    {
      id: 22,
      comparison_group: 'release-ab-2026-08',
      target_release_key: 'interview-agent@1.1',
      status: 'completed',
      items: [],
    },
  ],
}

async function mockSharedApis(page) {
  await page.route('**/api/admin/**', route => route.fulfill({ json: [] }))
  await page.route('**/api/admin/evals/runs**', route => route.fulfill({ json: runsPayload }))
  await page.route('**/api/admin/evals/reviews**', route => route.fulfill({ json: { reviews: [] } }))
  await page.route('**/api/auth/**', route => route.fulfill({ json: { id: 1, username: 'admin', is_admin: true } }))
  await page.route('**/api/data/**', route => route.fulfill({ json: [] }))
  await page.route('**/api/coding/**', route => route.fulfill({ json: [] }))
}

function readSource(relativePath) {
  return readFileSync(resolve(process.cwd(), relativePath), 'utf8')
}

test.describe('组件与视觉一致性', () => {
  test('人工 A/B 页面使用统一 Select，不渲染原生 select', async ({ page }) => {
    await mockSharedApis(page)
    await page.goto('/admin/evals/reviews?preview=1')

    await expect(page.getByText('对比组')).toBeVisible({ timeout: 15000 })
    await expect(page.locator('[data-slot="select-trigger"]')).toHaveCount(4)
    await expect(page.locator('select')).toHaveCount(0)
  })

  test('目标组件共享图标、选择器和图表 token', () => {
    const userMenu = readSource('src/components/business/UserMenu.vue')
    const questionCard = readSource('src/components/business/QuestionCard.vue')
    const deckManager = readSource('src/components/business/PracticeDeckManager.vue')
    const reviewView = readSource('src/views/admin/EvaluationReviewsView.vue')
    const starChart = readSource('src/components/business/PracticeStarChart.vue')
    const quadChart = readSource('src/components/business/PracticeQuadChart.vue')

    expect(userMenu).toContain("from '@lucide/vue'")
    expect(questionCard).toContain("from '@lucide/vue'")
    expect(userMenu).not.toContain('<svg')
    expect(questionCard).not.toContain('<svg')
    expect(deckManager).toContain("from '@/components/ui/select'")
    expect(deckManager).not.toMatch(/<select\b/)
    expect(reviewView).toContain("from '@/components/ui/select'")
    expect(reviewView).not.toMatch(/<select\b/)
    expect(starChart).toContain("from '@/utils/chartTokens.js'")
    expect(quadChart).toContain("from '@/utils/chartTokens.js'")
    expect(starChart).not.toMatch(/#[0-9a-f]{3,8}/i)
    expect(quadChart).not.toMatch(/#[0-9a-f]{3,8}/i)
  })
})
