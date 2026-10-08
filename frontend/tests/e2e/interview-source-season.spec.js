import { expect, test } from '@playwright/test'
const user = { id: 701, username: 'interview_sources', is_admin: false, bank_mode: 'public', current_position_id: 1, current_position: '后端开发工程师' }
async function mockApi(page) {
  const locationRequests = []
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname
    if (!path.startsWith('/api/')) return route.continue()
    if (path === '/api/auth/refresh') return route.fulfill({ json: { token: 'test-token', user } })
    if (path === '/api/auth/me') return route.fulfill({ json: user })
    if (path === '/api/data/interview') {
      const pageNumber = Number(url.searchParams.get('page') || 1), pageSize = Math.min(100, Number(url.searchParams.get('page_size') || 20)), season = url.searchParams.get('season')
      const rows = Array.from({ length: 140 }, (_, index) => ({ id: index + 1, '公司': `公司-${index + 1}`, season: index < 100 ? '2026春招' : '2025秋招', '来源链接': `https://example.test/interview/${index + 1}`, '具体题目清单': '跨页面经题目', owner_id: user.id })).filter(row => !season || row.season === season)
      return route.fulfill({ json: { items: rows.slice((pageNumber - 1) * pageSize, pageNumber * pageSize), total: rows.length } })
    }
    if (/^\/api\/data\/interview\/(120|140)\/location$/.test(path)) {
      const id = Number(path.split('/')[4])
      locationRequests.push(Object.fromEntries(url.searchParams.entries()))
      return route.fulfill({ json: { interview_id: id, page: Math.ceil(id / 20), page_size: 20, rank: id, position_id: 1, position_name: user.current_position } })
    }
    if (path === '/api/master-bank') return route.fulfill({ json: { items: [{ id: 800, question: '跨页面经来源题目', answer: '参考答案', answer_sources: [], cat1: '后端', frequency: 1, sources: [{ url: 'https://example.test/interview/140', company: '跨页来源公司', round: '一面' }, { url: 'https://example.test/interview/120', company: '第二来源公司', round: '一面' }] }], total: 1 } })
    if (path === '/api/data/jd') return route.fulfill({ json: { items: [], total: 0 } })
    if (path === '/api/profile') return route.fulfill({ json: { settings: {}, available_seasons: [] } })
    return route.fulfill({ json: [] })
  })
  return locationRequests
}

test('招聘季选项包括100条后的数据，筛选后保留其他招聘季', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  await page.getByRole('button', { name: '面经库' }).click()
  const seasonFilter = page.getByText('招聘季筛选：').locator('xpath=..').getByRole('combobox')
  await seasonFilter.click()
  await expect(page.getByRole('option', { name: '2025秋招', exact: true })).toBeVisible()
  await page.getByRole('option', { name: '2025秋招', exact: true }).click()
  await expect(page.getByText('共 40 条，第 1/2 页')).toBeVisible()
  await seasonFilter.click()
  await expect(page.getByRole('option', { name: '2026春招', exact: true })).toBeVisible()
})

test('题库来源可以定位未加载页中的面经，页码由location接口提供', async ({ page }) => {
  const locationRequests = await mockApi(page)
  await page.goto('/')
  await page.getByRole('button', { name: /选择题目：跨页/ }).click()
  await page.getByRole('button', { name: '来源详情' }).click()
  await page.getByText('跨页来源公司', { exact: false }).click()
  await expect(page.locator('[data-row-id="140"]')).toBeVisible()
  await expect(page.getByText('共 140 条，第 7/7 页')).toBeVisible()
  expect(locationRequests).toHaveLength(1)
  expect(locationRequests[0]).toMatchObject({ page_size: '20', sort: 'created_at_desc', scope: 'all', position_id: '1' })
})


test('连续查看两个不同来源时分别定位，不被上一次高亮跳过', async ({ page }) => {
  const locationRequests = await mockApi(page)
  await page.goto('/')
  await page.getByRole('button', { name: /选择题目：跨页/ }).click()
  await page.getByRole('button', { name: '来源详情' }).click()
  await page.getByText('跨页来源公司', { exact: false }).click()
  await expect(page.locator('[data-row-id="140"]')).toBeVisible()
  await page.getByRole('button', { name: '高频题库' }).click()
  await page.getByRole('button', { name: /选择题目：跨页/ }).click()
  await page.getByRole('button', { name: '来源详情' }).click()
  await page.getByText('第二来源公司', { exact: false }).click()
  await expect(page.locator('[data-row-id="120"]')).toBeVisible()
  await expect(page.locator('[data-row-id="120"]')).toHaveClass(/highlight-row/)
  await expect(page.getByText('共 140 条，第 6/7 页')).toBeVisible()
  expect(locationRequests).toHaveLength(2)
})

test('预览模式面经来源定位只使用本地数据，不依赖后端', async ({ page }) => {
  const locationRequests = []
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) return route.continue()
    if (/\/interview\/\d+\/location$/.test(path)) locationRequests.push(path)
    return route.fulfill({ status: 401, json: { detail: '未登录' } })
  })
  await page.goto('/master-bank?preview=1')
  await page.getByRole('button', { name: /选择题目：Vue 3/ }).click()
  await page.getByRole('button', { name: '来源详情' }).click()
  await page.locator('span.cursor-pointer').filter({ hasText: '字节' }).click()
  await expect(page).toHaveURL(/\/interview\?preview=1/)
  await expect(page.locator('[data-row-id="8201"]')).toBeVisible()
  await expect(page.locator('[data-row-id="8201"]')).toHaveClass(/highlight-row/)
  expect(locationRequests).toEqual([])
})

test('离开面经页后再次点击同一来源会重新定位目标页', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  await page.getByRole('button', { name: /选择题目：跨页/ }).click()
  await page.getByRole('button', { name: '来源详情' }).click()
  await page.getByText('跨页来源公司', { exact: false }).click()
  await expect(page.locator('[data-row-id="140"]')).toBeVisible()
  await page.locator('[data-slot="pagination-previous"]').click()
  await expect(page.getByText('共 140 条，第 6/7 页')).toBeVisible()
  await page.getByRole('button', { name: '高频题库' }).click()
  await page.getByRole('button', { name: /选择题目：跨页/ }).click()
  await page.getByRole('button', { name: '来源详情' }).click()
  await page.getByText('跨页来源公司', { exact: false }).click()
  await expect(page.locator('[data-row-id="140"]')).toBeVisible()
  await expect(page.getByText('共 140 条，第 7/7 页')).toBeVisible()
})
