/** AC-001/002: interview server pagination and result location. */
import { expect, test } from '@playwright/test'

const USER = {
  id: 101,
  username: 'pagination_user',
  is_admin: false,
  bank_mode: 'public',
  current_position_id: 1,
  current_position: 'P1',
}

const RESULT_TASK = {
  import_id: 'imp-result-p2',
  revision: 5,
  status: 'completed',
  target_intent: 'private',
  attempt_no: 1,
  review_status: null,
  stage: 'complete',
  position_id: 2,
  position_name: 'P2',
  result: { interview_id: 9001, position_id: 2 },
  error: null,
  allowed_actions: ['open_result'],
  created_at: '2026-10-01T10:00:00Z',
  updated_at: '2026-10-01T10:01:00Z',
}

function interviewRow(id, season, company = `面经-${id}`) {
  return {
    id,
    '来源链接': `https://example.test/interview/${id}`,
    '公司': company,
    '面试轮次': '一面',
    '考察重点': '分页验收',
    '具体题目清单': `题目-${id}`,
    '难易程度': '中等',
    season,
    owner_id: 101,
    created_at: '2026-10-01T10:00:00',
  }
}

async function mockApi(page, { task = null, locationStatus = 200 } = {}) {
  const interviewRequests = []
  const locationRequests = []
  let currentPositionId = 1

  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    if (!path.startsWith('/api/')) return route.continue()

    if (path === '/api/auth/refresh') {
      return route.fulfill({ json: { token: 'pagination-token', user: USER } })
    }
    if (path === '/api/auth/me') return route.fulfill({ json: USER })
    if (path === '/api/data/interview' && request.method() === 'GET') {
      const query = Object.fromEntries(url.searchParams.entries())
      interviewRequests.push(query)
      const pageNumber = Number(query.page || 1)
      const pageSize = Number(query.page_size || 20)
      const positionId = Number(query.position_id || currentPositionId)
      const season = query.season || ''
      const total = season === '2025秋招' ? 7 : 45
      const offset = (pageNumber - 1) * pageSize
      const count = Math.max(0, Math.min(pageSize, total - offset))
      const items = Array.from({ length: count }, (_, index) => {
        const absoluteIndex = offset + index
        if (positionId === 2 && absoluteIndex === 40) {
          return interviewRow(9001, '2026春招', 'P2 目标面经')
        }
        return interviewRow(6000 + (positionId * 1000) + absoluteIndex, season || (absoluteIndex % 2 ? '2025秋招' : '2026春招'))
      })
      return route.fulfill({ json: { items, total, page: pageNumber, page_size: pageSize } })
    }
    if (/^\/api\/data\/interview\/\d+\/location$/.test(path)) {
      locationRequests.push({ path, query: Object.fromEntries(url.searchParams.entries()) })
      if (locationStatus !== 200) {
        return route.fulfill({ status: locationStatus, json: { detail: '面经不存在' } })
      }
      return route.fulfill({
        json: { interview_id: 9001, page: 3, page_size: 20, rank: 41, position_id: 2, position_name: 'P2' },
      })
    }
    if (path === '/api/profile/position' && request.method() === 'PUT') {
      currentPositionId = Number(request.postDataJSON()?.position_id || 1)
      return route.fulfill({ json: { current_position_id: currentPositionId, current_position: `P${currentPositionId}` } })
    }
    if (path.startsWith('/api/profile')) {
      return route.fulfill({
        json: {
          id: USER.id,
          settings: { current_job_position: `P${currentPositionId}`, current_job_position_id: currentPositionId },
          current_position_id: currentPositionId,
          available_seasons: ['2025秋招', '2026春招'],
          llm_configured: true,
        },
      })
    }
    if (path === '/api/positions' || path === '/api/positions/') {
      return route.fulfill({ json: { positions: [{ id: 1, name: 'P1' }, { id: 2, name: 'P2' }] } })
    }
    if (path === '/api/data/jd') return route.fulfill({ json: { items: [], total: 0 } })
    if (path === '/api/master-bank') return route.fulfill({ json: { items: [], total: 0, overall_total: 0 } })
    if (path === '/api/upload-imports') {
      const items = task ? [task] : []
      return route.fulfill({ json: { items, total: items.length, page: 1, page_size: 20 } })
    }
    if (path === '/api/submit-jobs/active') return route.fulfill({ json: [] })
    if (path === '/api/analytics' || path === '/api/practice/stats' || path === '/api/practice-stats') {
      return route.fulfill({ json: {} })
    }
    return route.fulfill({ json: {} })
  })

  return { interviewRequests, locationRequests }
}

async function openInterviewPage(page, options) {
  const evidence = await mockApi(page, options)
  await page.goto('/')
  await page.getByRole('button', { name: '面经库' }).click()
  await expect(page.getByRole('heading', { name: '面经库' })).toBeVisible()
  await expect(page.locator('[data-row-id]').first()).toBeVisible()
  return evidence
}

test('首屏、翻页、排序、筛选和 page size 都走服务端当前页', async ({ page }) => {
  const { interviewRequests } = await openInterviewPage(page)

  await expect(page.locator('[data-row-id]')).toHaveCount(20)
  await expect.poll(() => interviewRequests.some((query) => query.page === '1' && query.page_size === '20')).toBe(true)

  await page.locator('[data-slot="pagination-next"]').click()
  await expect(page.getByText('共 45 条，第 2/3 页')).toBeVisible()
  await expect(page.locator('[data-row-id]')).toHaveCount(20)
  await expect.poll(() => interviewRequests.some((query) => query.page === '2' && query.page_size === '20')).toBe(true)

  await page.locator('button').filter({ hasText: '上传日期' }).click()
  await expect(page.getByText('共 45 条，第 1/3 页')).toBeVisible()
  await expect.poll(() => interviewRequests.some((query) => query.page === '1' && query.page_size === '20' && query.sort === 'created_at_asc')).toBe(true)

  await page.locator('[data-slot="pagination-next"]').click()
  await expect(page.getByText('共 45 条，第 2/3 页')).toBeVisible()
  const seasonFilter = page.getByText('招聘季筛选：').locator('xpath=..').getByRole('combobox')
  await seasonFilter.click()
  await page.getByRole('option', { name: '2025秋招', exact: true }).click()
  await expect(page.locator('[data-row-id]')).toHaveCount(7)
  await expect.poll(() => interviewRequests.some((query) => query.page === '1' && query.page_size === '20' && query.season === '2025秋招')).toBe(true)

  const seasonTrigger = page.getByText('2025秋招', { exact: true }).first()
  await seasonTrigger.click()
  await page.getByRole('option', { name: '全部', exact: true }).click()
  await page.locator('[data-slot="pagination-next"]').click()
  await expect(page.getByText('共 45 条，第 2/3 页')).toBeVisible()
  const pagination = page.locator('[data-slot="pagination"]')
  await pagination.getByRole('combobox').click()
  await page.getByRole('option', { name: '50', exact: true }).click()
  await expect.poll(() => interviewRequests.some((query) => query.page === '1' && query.page_size === '50')).toBe(true)
  await expect(page.locator('[data-row-id]')).toHaveCount(45)
})

test('P1 第 2 页的任务只在用户点查看结果时切换并定位到 P2', async ({ page }) => {
  const { interviewRequests, locationRequests } = await openInterviewPage(page, { task: RESULT_TASK })
  await page.locator('[data-slot="pagination-next"]').click()
  await expect(page.getByText('共 45 条，第 2/3 页')).toBeVisible()
  await page.getByRole('button', { name: '上传任务中心' }).click()
  await expect(page).toHaveURL(/\/interview$/)
  await expect(page.getByText('共 45 条，第 2/3 页')).toBeVisible()

  await page.getByRole('button', { name: '查看结果' }).click()
  await expect.poll(() => locationRequests.length).toBe(1)
  await expect(page.locator('[data-row-id="9001"]')).toBeVisible()
  await expect(page.locator('[data-row-id="9001"]')).toHaveClass(/highlight-row/)
  await expect(page.getByText('共 45 条，第 3/3 页')).toBeVisible()
  await expect.poll(() => interviewRequests.some((query) => query.position_id === '2' && query.page === '3' && query.page_size === '20')).toBe(true)
})

test('目标面经被删除或无权访问时提示错误且不跳页', async ({ page }) => {
  await openInterviewPage(page, { task: RESULT_TASK, locationStatus: 404 })
  await page.locator('[data-slot="pagination-next"]').click()
  await expect(page.getByText('共 45 条，第 2/3 页')).toBeVisible()
  await page.getByRole('button', { name: '上传任务中心' }).click()
  await page.getByRole('button', { name: '查看结果' }).click()
  const center = page.getByRole('region', { name: '上传任务中心' })
  await expect(center.getByText('面经已删除或无权访问')).toBeVisible()
  await expect(page).toHaveURL(/\/interview$/)
  await expect(page.getByText('共 45 条，第 2/3 页')).toBeVisible()
})
