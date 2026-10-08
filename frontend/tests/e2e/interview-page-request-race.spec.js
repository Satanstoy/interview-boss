import { expect, test } from '@playwright/test'

const user = {
  id: 701,
  username: 'interview_page_race',
  is_admin: false,
  bank_mode: 'public',
  current_position_id: 1,
  current_position: '后端开发工程师',
}

const row = (id, company) => ({
  id,
  '公司': company,
  season: '2026届春招',
  '面试轮次': '一面',
  '考察重点': '请求竞态回归测试',
  '具体题目清单': `${company}面经内容`,
  '难易程度': '中等',
  created_at: '2026-03-18T09:00:00',
  owner_id: user.id,
  '来源链接': '',
})

test('a slower previous sort response cannot replace the current interview page', async ({ page }) => {
  let resolveStaleRequestStarted
  let resolveStaleResponseFinished
  const staleRequestStarted = new Promise(resolve => { resolveStaleRequestStarted = resolve })
  const staleResponseFinished = new Promise(resolve => { resolveStaleResponseFinished = resolve })

  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (!path.startsWith('/api/')) {
      await route.continue()
      return
    }

    if (path === '/api/auth/refresh') {
      await route.fulfill({ json: { token: 'race-test-token', user } })
    } else if (path === '/api/auth/me') {
      await route.fulfill({ json: user })
    } else if (path === '/api/auth/logout') {
      await route.fulfill({ json: { status: 'success' } })
    } else if (path === '/api/data/jd') {
      await route.fulfill({ json: [] })
    } else if (path === '/api/data/interview') {
      const pageSize = url.searchParams.get('page_size')
      const sort = url.searchParams.get('sort')
      if (pageSize === '20' && sort === 'created_at_desc') {
        resolveStaleRequestStarted()
        await new Promise(resolve => setTimeout(resolve, 800))
        await route.fulfill({ json: { items: [row(1, '旧排序响应')], total: 1 } })
        resolveStaleResponseFinished()
      } else if (pageSize === '20' && sort === 'created_at_asc') {
        await route.fulfill({ json: { items: [row(2, '当前排序响应')], total: 1 } })
      } else {
        await route.fulfill({ json: { items: [], total: 0 } })
      }
    } else if (path === '/api/master-bank') {
      await route.fulfill({ json: { items: [], total: 0, overall_total: 0 } })
    } else if (path === '/api/analytics' || path === '/api/practice/stats') {
      await route.fulfill({ json: {} })
    } else if (path === '/api/profile') {
      await route.fulfill({ json: { settings: {}, available_seasons: [] } })
    } else {
      await route.fulfill({ json: [] })
    }
  })

  await page.goto('/interview')
  await staleRequestStarted
  const sortButton = page.locator('button').filter({ hasText: '上传日期' }).first()
  await expect(sortButton).toBeVisible()
  await sortButton.click()
  await expect(page.getByText('当前排序响应', { exact: true })).toBeVisible()
  await staleResponseFinished
  await expect(page.getByText('当前排序响应', { exact: true })).toBeVisible()
  await expect(page.getByText('旧排序响应', { exact: true })).toHaveCount(0)
})
