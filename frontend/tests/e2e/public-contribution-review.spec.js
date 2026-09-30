/**
 * 公共贡献审核 E2E（AC-015 / acceptance.md 第 194 行）
 *
 * 所有 API 通过 page.route() mock：
 * - 管理员可从用户菜单打开「审核题库」面板，看到待审公共贡献；
 * - approve 后该项从待审列表移除并提示成功；reject 同理；
 * - 面经/JD 共用同一审核入口（sourceTabs 切换）。
 */
import { test, expect } from '@playwright/test'

const MOCK_ADMIN = {
  id: 201,
  username: 'admin',
  is_admin: 1,
  bank_mode: 'public',
  current_position_id: 1,
  current_position: '后端开发工程师',
}

const CONTRIBUTION = {
  id: 7001,
  source_type: 'interview',
  source_id: 101,
  req_id: 'req-e2e-1',
  source_summary: {
    company: '字节',
    round: '一面',
    source_url: 'https://example.com/interview-1',
    questions_list: ['TCP 三次握手', 'Redis 持久化'],
  },
  review_projection: {
    company: '字节',
    round: '一面',
    source_url: 'https://example.com/interview-1',
    questions_list: ['TCP 三次握手', 'Redis 持久化'],
  },
  status: 'pending_review',
  created_at: '2026-09-30T08:00:00Z',
}

const MOCK_CONTRIBUTIONS = { items: [CONTRIBUTION], total: 1 }

async function mockApi(page) {
  await page.route('**/api/auth/**', (route) =>
    route.fulfill({ json: { token: 'e2e-token', user: MOCK_ADMIN } }),
  )
  await page.route('**/api/admin/public-contributions**', (route) => {
    if (route.request().url().includes('/approve') || route.request().url().includes('/reject')) {
      return route.fallback()
    }
    return route.fulfill({ json: MOCK_CONTRIBUTIONS })
  })
  await page.route('**/api/admin/public-contributions/7001/approve', (route) =>
    route.fulfill({ json: { status: 'approved', id: 7001 } }),
  )
  await page.route('**/api/admin/public-contributions/7001/reject', (route) =>
    route.fulfill({ json: { status: 'rejected', id: 7001 } }),
  )
  // 审核面板还拉旧版待审题（legacy），必须 mock 返回空
  await page.route('**/api/master-bank/pending', (route) => route.fulfill({ json: { items: [] } }))
  // 审核面板依赖题库数据上下文（fetchTableData 在 reviewed 后触发）
  await page.route('**/api/data/jd?**', (route) => route.fulfill({ json: { items: [], total: 0 } }))
  await page.route('**/api/data/interview?**', (route) => route.fulfill({ json: { items: [], total: 0 } }))
  await page.route('**/api/master-bank?**', (route) => route.fulfill({ json: { items: [], total: 0 } }))
}

test('管理员打开审核面板并批准待审公共贡献', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  // 用户菜单 → 审核题库
  await page.getByRole('button', { name: /admin/ }).first().click()
  await page.getByRole('button', { name: /审核题库/ }).click()

  await expect(page.getByText('公共贡献审核')).toBeVisible()
  // 待审贡献行出现（含操作按钮）
  await expect(page.getByRole('button', { name: '通过' }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: '拒绝' }).first()).toBeVisible()

  await page.getByRole('button', { name: '通过' }).first().click()
  await expect(page.getByText('已通过审核').first()).toBeVisible()
  // approve 后从待审列表移除
  await expect(page.getByText(/暂无待审核贡献/).first()).toBeVisible()
})

test('管理员可拒绝公共贡献', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  await page.getByRole('button', { name: /admin/ }).first().click()
  await page.getByRole('button', { name: /审核题库/ }).click()

  await expect(page.getByText('公共贡献审核')).toBeVisible()
  await page.getByRole('button', { name: /拒绝/ }).first().click()
  await expect(page.getByText('已拒绝').first()).toBeVisible()
  await expect(page.getByText(/暂无待审核贡献/).first()).toBeVisible()
})