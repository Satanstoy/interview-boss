import { expect, test } from '@playwright/test'

// ---- Mock data ----

const runDetailPayload = {
  id: 12,
  status: 'completed',
  target_release_key: 'interview-agent@1.0',
  evaluation_release_key: 'interview-eval@1.0',
  total_items: 5,
  completed_items: 3,
  failed_items: 1,
  quality_status: 'failed',
  summary: { metric_summary: { score: { final_mean: 0.72, deterministic_mean: 0.70, judge_mean: 0.74 } } },
  items: [
    { id: 101, case_key: 'jd_basic', replication_index: 1, seed: 1, status: 'completed', contract_status: 'valid', hard_gate_status: 'passed', judge_status: 'succeeded', score: 0.85, result: { observation: { payload: { tool_metrics: { call_count: 2, failed_call_count: 0 } } }, score: { score: 0.85, judge_score: 0.90 } } },
    { id: 102, case_key: 'tool_timing', replication_index: 1, seed: 2, status: 'failed', contract_status: 'valid', hard_gate_status: 'failed', judge_status: 'succeeded', score: 0.45, result: { observation: { payload: { tool_metrics: { call_count: 1, failed_call_count: 1 } }, hard_assertions: [{ id: 'tool_calls_valid', passed: false, evidence: '工具时机不符合' }] }, score: { score: 0.45, judge_score: 0.50 } } },
    { id: 103, case_key: 'resume_match', replication_index: 1, seed: 3, status: 'completed', contract_status: 'valid', hard_gate_status: 'passed', judge_status: 'succeeded', score: 0.78, result: { observation: { payload: { metrics: { field_coverage: 0.80, question_recall: 0.75 } } }, score: { score: 0.78, judge_score: 0.80 } } },
    { id: 104, case_key: 'tagging_basic', replication_index: 1, seed: 4, status: 'completed', contract_status: 'valid', hard_gate_status: 'passed', judge_status: 'succeeded', score: 0.91, result: { observation: { payload: { metrics: { taxonomy_validity: 0.95, classification_accuracy: 0.90 } } }, score: { score: 0.91, judge_score: 0.92 } } },
    { id: 105, case_key: 'experience_extract', replication_index: 1, seed: 5, status: 'running', contract_status: 'pending', hard_gate_status: 'pending', judge_status: 'pending', score: null, result: { observation: { payload: {} } } },
  ],
};

const runItemPayload = {
  item: runDetailPayload.items[1],
  case: {
    case_key: 'tool_timing',
    scenario_key: 'tool_timing',
    input_snapshot: { candidate_view: { opening: '你好' } },
    contract: { hard_assertions: [{ id: 'tool_calls_valid' }] },
  },
  attempts: [{ id: 401, attempt_index: 1, status: 'succeeded', raw_observation: {} }],
  artifacts: [],
};

async function mockAuth(page) {
  await page.route('**/api/auth/**', route => {
    if (route.request().url().includes('/refresh')) {
      return route.fulfill({ json: { token: 'mock-token', user: { id: 1, username: 'admin', is_admin: true } } });
    }
    return route.fulfill({ json: { id: 1, username: 'admin', is_admin: true } });
  });
  await page.route('**/api/data/**', route => route.fulfill({ json: [] }));
  await page.route('**/api/analytics**', route => route.fulfill({ json: {} }));
  await page.route('**/api/practice/**', route => route.fulfill({ json: [] }));
  await page.route('**/api/profile**', route => route.fulfill({ json: { positions: [] } }));
  await page.route('**/api/interview**', route => route.fulfill({ json: [] }));
  await page.route('**/api/coding/**', route => route.fulfill({ json: [] }));
  await page.route('**/api/knowledge**', route => route.fulfill({ json: { nodes: [], edges: [] } }));
  await page.route('**/api/admin/**', route => {
    if (route.request().url().includes('/api/admin/evals/')) return route.fallback();
    return route.fulfill({ json: [] });
  });
}

test.describe('评测工作台布局', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page);
    await page.route('**/api/admin/evals/runs/12', route => route.fulfill({ json: runDetailPayload }));
    await page.route('**/api/admin/evals/runs/12/items/**', route => route.fulfill({ json: runItemPayload }));
    await page.route('**/api/admin/evals/runs/12/events', route => route.fulfill({ json: {} }));
  });

  test('左侧显示 Case 导航栏，包含所有 Case', async ({ page }) => {
    await page.goto('/admin/evals/runs/12?preview=1');

    // 应该有 Case 导航栏
    const navigator = page.locator('[aria-label="Case 导航"]');
    await expect(navigator).toBeVisible({ timeout: 15000 });

    // 应该渲染 5 个导航条目
    const navItems = navigator.locator('.eval-case-item');
    await expect(navItems).toHaveCount(5);
  });

  test('失败 Case 排在导航栏顶部（issue-prioritization）', async ({ page }) => {
    await page.goto('/admin/evals/runs/12?preview=1');

    const navigator = page.locator('[aria-label="Case 导航"]');
    await expect(navigator).toBeVisible({ timeout: 15000 });

    // 第一个导航条目应该是 tool_timing（status=failed）
    const firstNavItem = navigator.locator('.eval-case-item').first();
    await expect(firstNavItem).toContainText('tool_timing');
  });

  test('右侧显示证据面板', async ({ page }) => {
    await page.goto('/admin/evals/runs/12?preview=1');

    // 证据面板应该自动显示（自动选中第一个失败 Case）
    const evidencePanel = page.locator('[aria-label="Case 证据面板"]');
    await expect(evidencePanel).toBeVisible({ timeout: 15000 });
    await expect(evidencePanel).toContainText('候选人可见输入');
  });

  test('顶部显示进度条和 Case 计数', async ({ page }) => {
    await page.goto('/admin/evals/runs/12?preview=1');

    // 应该显示 Case 进度
    const progress = page.locator('[aria-label="Case 进度"]');
    await expect(progress).toBeVisible({ timeout: 15000 });
    await expect(progress).toContainText('5');  // total items
  });

  test('J/K 键盘切换 Case', async ({ page }) => {
    await page.goto('/admin/evals/runs/12?preview=1');

    const navigator = page.locator('[aria-label="Case 导航"]');
    await expect(navigator).toBeVisible({ timeout: 15000 });

    // 初始选中第一个（失败的 tool_timing）
    const firstItem = navigator.locator('.eval-case-item').first();
    await expect(firstItem).toHaveAttribute('aria-current', 'true');

    // 按 J 切换到下一个
    await page.keyboard.press('j');
    const secondItem = navigator.locator('.eval-case-item').nth(1);
    await expect(secondItem).toHaveAttribute('aria-current', 'true');

    // 按 K 回到上一个
    await page.keyboard.press('k');
    await expect(firstItem).toHaveAttribute('aria-current', 'true');
  });
});