import { expect, test } from '@playwright/test'

const activeExperiment = {
  id: 88,
  experiment_key: 'frontend-running-88',
  status: 'running',
  total_runs: 1,
  completed_runs: 0,
  failed_runs: 0,
  cancelled_runs: 0,
  total_items: 12,
  completed_items: 5,
  failed_items: 1,
  created_at: '2026-08-20T10:00:00Z',
  runs: [{
    run_id: 801,
    target_type: 'interview',
    target_release_key: 'interview-agent@1.1',
    evaluation_release_key: 'interview-eval@1.1',
    benchmark_suite_release_key: 'interview-benchmark@1.1',
    project_harness_key: 'interview-harness',
    project_harness_version: '1.1',
    status: 'running',
    total_items: 12,
    completed_items: 5,
    failed_items: 1,
    distribution: { total: 12, passed: 3, poor: 1, failed: 1, pending: 7 },
    created_at: '2026-08-20T10:00:00Z',
  }],
}

async function mockShellApis(page) {
  await page.route('**/api/auth/**', route => route.fulfill({
    json: route.request().url().includes('/refresh')
      ? { token: 'mock-token', user: { id: 1, username: 'admin', is_admin: true } }
      : { id: 1, username: 'admin', is_admin: true },
  }))
  await page.route('**/api/data/**', route => route.fulfill({ json: [] }))
  await page.route('**/api/analytics**', route => route.fulfill({ json: {} }))
  await page.route('**/api/practice/**', route => route.fulfill({ json: [] }))
  await page.route('**/api/practice-stats', route => route.fulfill({ json: {} }))
  await page.route('**/api/master-bank**', route => route.fulfill({ json: { questions: [], total: 0, has_more: false } }))
  await page.route('**/api/profile**', route => route.fulfill({ json: { positions: [] } }))
  await page.route('**/api/interview**', route => route.fulfill({ json: [] }))
  await page.route('**/api/coding/**', route => route.fulfill({ json: [] }))
  await page.route('**/api/knowledge**', route => route.fulfill({ json: { nodes: [], edges: [] } }))
}

async function mockEvaluationApis(page) {
  let cancelRequests = 0

  await page.route('**/api/admin/evals/releases**', route => route.fulfill({ json: { releases: [] } }))
  await page.route('**/api/admin/evals/capabilities', route => route.fulfill({ json: { targets: [] } }))
  await page.route('**/api/admin/evals/benchmarks', route => route.fulfill({ json: { suites: [] } }))
  await page.route('**/api/admin/evals/harness-releases', route => route.fulfill({ json: { harness_releases: [] } }))
  await page.route('**/api/admin/evals/experiments/88/cancel', route => {
    cancelRequests += 1
    return route.fulfill({ json: { id: 88, status: 'cancelled' } })
  })
  await page.route('**/api/admin/evals/experiments', route => route.fulfill({ json: { experiments: [activeExperiment] } }))

  return {
    get cancelRequests() {
      return cancelRequests
    },
  }
}

async function gotoExperiments(page) {
  await mockShellApis(page)
  const requests = await mockEvaluationApis(page)
  await page.goto('/admin/evals/experiments?preview=1')
  await expect(page.locator('[data-evaluation-workbench]')).toBeVisible()
  await expect(page.locator('[data-mobile-row-card="active-experiment-88"], [data-testid="active-experiment-row-88"]')).toHaveCount(1)
  return requests
}

test.describe('UI/UX operation consistency', () => {
  test('cancelling an active experiment requires confirmation before the API request', async ({ page }) => {
    const requests = await gotoExperiments(page)
    const row = page.locator('[data-testid="active-experiment-row-88"]')

    await row.getByRole('button', { name: '取消', exact: true }).click()
    await expect(page.getByRole('alertdialog')).toContainText('确认取消评测实验')
    await expect(page.getByRole('alertdialog')).toContainText('已开始的实验会被终止')
    await expect(row.getByTestId('active-experiment-cancel')).toBeDisabled()
    expect(requests.cancelRequests).toBe(0)

    await page.getByRole('alertdialog').getByRole('button', { name: '取消', exact: true }).click()
    await expect(page.getByRole('alertdialog')).toHaveCount(0)
    expect(requests.cancelRequests).toBe(0)

    await row.getByRole('button', { name: '取消', exact: true }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: '确认取消', exact: true }).click()
    await expect(page.getByText('评测实验已取消')).toBeVisible()
    expect(requests.cancelRequests).toBe(1)
  })

  test('active experiments render as reachable cards on a narrow viewport', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await gotoExperiments(page)

    await expect(page.locator('table')).toBeHidden()
    const card = page.locator('[data-mobile-row-card="active-experiment-88"]')
    await expect(card).toBeVisible()
    await expect(card).toHaveAttribute('data-testid', 'active-experiment-row-88')
    await expect(card.getByRole('button', { name: '详情' })).toBeVisible()
    await expect(card.getByRole('button', { name: '取消', exact: true })).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)
    expect(overflow).toBe(false)
  })

  test('compact account menu exposes a stable accessible name and expanded state', async ({ page }) => {
    await mockShellApis(page)
    await page.goto('/master-bank?preview=1')
    await page.getByRole('button', { name: '收起侧栏' }).click()

    const accountButton = page.getByRole('button', { name: '账户菜单' })
    await expect(accountButton).toHaveAttribute('aria-haspopup', 'menu')
    await expect(accountButton).toHaveAttribute('aria-expanded', 'false')
    await accountButton.click()
    await expect(accountButton).toHaveAttribute('aria-expanded', 'true')
    await page.keyboard.press('Escape')
    await expect(accountButton).toHaveAttribute('aria-expanded', 'false')
  })
})
