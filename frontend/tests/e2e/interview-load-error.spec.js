import { expect, test } from '@playwright/test'

const user = { id: 701, username: 'interview_load_error', is_admin: false, bank_mode: 'public', current_position_id: 1, current_position: '后端开发工程师' }
const row = id => ({ id, '公司': `公司-${id}`, season: '2026春招', '具体题目清单': '错误恢复测试', owner_id: user.id })

async function mockApi(page, shouldFail) {
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    if (!url.pathname.startsWith('/api/')) return route.continue()
    if (url.pathname === '/api/auth/refresh') return route.fulfill({ json: { token: 'test-token', user } })
    if (url.pathname === '/api/auth/me') return route.fulfill({ json: user })
    if (url.pathname === '/api/data/interview') {
      const pageNumber = Number(url.searchParams.get('page') || 1)
      const pageSize = Number(url.searchParams.get('page_size') || 20)
      if (pageSize !== 500 && shouldFail(pageNumber)) {
        return route.fulfill({ status: 500, json: { detail: 'database unavailable' } })
      }
      const items = Array.from({ length: pageSize === 500 ? 40 : 20 }, (_, index) => row((pageNumber - 1) * 20 + index + 1))
      return route.fulfill({ json: { items, total: 40 } })
    }
    if (url.pathname === '/api/data/jd') return route.fulfill({ json: { items: [], total: 0 } })
    if (url.pathname === '/api/master-bank') return route.fulfill({ json: { items: [], total: 0 } })
    if (url.pathname === '/api/profile') return route.fulfill({ json: { settings: {}, available_seasons: [] } })
    return route.fulfill({ json: [] })
  })
}

test('面经接口失败显示错误而非空列表，重试可以恢复', async ({ page }) => {
  let fail = true
  await mockApi(page, () => fail)
  await page.goto('/')
  await page.getByRole('button', { name: '面经库' }).click()
  await expect(page.getByRole('alert').filter({ hasText: '面经加载失败' })).toBeVisible({ timeout: 15000 })
  await expect(page.getByText('暂无面经数据', { exact: true })).toHaveCount(0)
  fail = false
  await page.getByRole('button', { name: '重试加载面经' }).click()
  await expect(page.locator('[data-row-id]')).toHaveCount(20)
  await expect(page.getByRole('alert').filter({ hasText: '面经加载失败' })).toHaveCount(0)
})

test('翻页失败不把旧页显示为新页，重试加载请求的页', async ({ page }) => {
  let fail = true
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await mockApi(page, pageNumber => fail && pageNumber === 2)
  await page.goto('/')
  await page.getByRole('button', { name: '面经库' }).click()
  await expect(page.locator('[data-row-id="1"]')).toBeVisible()
  await page.locator('[data-slot="pagination-next"]').click()
  await expect(page.getByRole('alert').filter({ hasText: '面经加载失败' })).toBeVisible({ timeout: 15000 })
  await expect(page.locator('[data-row-id]')).toHaveCount(0)
  fail = false
  await page.getByRole('button', { name: '重试加载面经' }).click()
  await expect(page.locator('[data-row-id="21"]')).toBeVisible()
  await expect(page.getByText('共 40 条，第 2/2 页')).toBeVisible()
  expect(errors).toEqual([])
})
