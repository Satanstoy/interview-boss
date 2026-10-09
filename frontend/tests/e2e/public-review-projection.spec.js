// UI uses mocked APIs; backend preview has separate real SQLite tests.
import { test, expect } from '@playwright/test'

for (const sourceType of ['interview', 'jd']) {
  test(`${sourceType}: edit, exclude, preview and revision-aware approval`, async ({ page }) => {
    const calls = []
    const detail = { id: 71, source_type: sourceType, revision: 7, status: 'pending_review',
      snapshot: { source: { company: 'PRIVATE_COMPANY', round: 'PRIVATE_ROUND', source_url: 'https://private.example', job_title: '原始岗位', tech_stack: 'TCP', focus: '网络', salary: 'PRIVATE_SALARY' } },
      items: sourceType === 'jd' ? [] : [
        { id: 91, ordinal: 0, snapshot: { question: 'FIRST_QUESTION', cat1: '网络', cat2: 'TCP', tags: ['tcp'], difficulty: '中等' } },
        { id: 92, ordinal: 1, snapshot: { question: 'EXCLUDED_QUESTION', cat1: '网络', cat2: 'TCP' } },
      ],
    }
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname
      if (!path.startsWith('/api/')) return route.continue()
      const body = route.request().postDataJSON()
      calls.push({ path, body })
      if (path === '/api/admin/public-contributions') return route.fulfill({ json: { items: [{ ...detail, summary: { item_count: detail.items.length } }] } })
      if (path === '/api/admin/public-contributions/71') return route.fulfill({ json: detail })
      if (path.endsWith('/preview')) return route.fulfill({ json: { revision: 7, projection: {
        source: body.review_fields.source,
        items: body.review_fields.items.filter(item => !body.excluded_item_ids.includes(item.item_id)),
        excluded_item_ids: body.excluded_item_ids,
      } } })
      if (path.endsWith('/approve')) return route.fulfill({ status: 409, json: { detail: '申请版本已变化' } })
      return route.fulfill({ json: { items: [] } })
    })
    await page.route('**/__review_projection', route => route.fulfill({ contentType: 'text/html', body: `
      <html><body><div id="app"></div><script type="module">
      import {createApp,ref,onMounted,h} from '/node_modules/.vite/deps/vue.js';
      import Review from '/src/components/business/AdminReview.vue';
      createApp({setup(){const visible=ref(false);onMounted(()=>visible.value=true);return()=>h(Review,{visible:visible.value})}}).mount('#app');
      </script></body></html>` }))
    await page.goto('/__review_projection')
    await page.getByRole('button', { name: '通过', exact: true }).click()
    await expect(page.getByText('审核详情', { exact: true })).toBeVisible()
    expect(calls.some(call => call.path.endsWith('/approve'))).toBe(false)
    await expect(page.getByLabel('公开公司')).toHaveValue('')
    await page.getByLabel('公开公司').fill('PUBLIC_COMPANY')
    if (sourceType === 'interview') {
      await page.getByLabel('题干 1').fill('PUBLIC_EDIT')
      await page.getByLabel('排除题目 2').check()
    } else {
      await expect(page.getByLabel('公开薪资')).toHaveValue('')
      await page.getByLabel('公开岗位名称').fill('公开岗位')
    }
    await page.getByRole('button', { name: '预览公开内容', exact: true }).click()
    await expect(page.getByTestId('review-projection-preview')).toContainText('PUBLIC_COMPANY')
    await expect(page.getByTestId('review-projection-preview')).not.toContainText('PRIVATE_COMPANY')
    if (sourceType === 'interview') {
      await expect(page.getByTestId('review-projection-preview')).toContainText('PUBLIC_EDIT')
      await expect(page.getByTestId('review-projection-preview')).not.toContainText('EXCLUDED_QUESTION')
    }
    await page.getByLabel('公开公司').fill('FINAL_PUBLIC_COMPANY')
    await expect(page.getByTestId('review-projection-preview')).toHaveCount(0)
    await expect(page.getByRole('button', { name: '确认通过', exact: true })).toBeDisabled()
    await page.getByRole('button', { name: '预览公开内容', exact: true }).click()
    await page.getByRole('button', { name: '确认通过', exact: true }).click()
    await expect(page.getByTestId('review-error')).toContainText('申请版本已变化')
    await expect(page.getByLabel('公开公司')).toHaveValue('FINAL_PUBLIC_COMPANY')
    await expect(page.getByRole('button', { name: '确认通过', exact: true })).toBeDisabled()
    const submitted = calls.find(call => call.path.endsWith('/approve')).body
    expect(submitted.expected_revision).toBe(7)
    expect(submitted.review_fields.source.company).toBe('FINAL_PUBLIC_COMPANY')
    expect(submitted.review_fields.source.source_url).toBeNull()
    if (sourceType === 'interview') expect(submitted.excluded_item_ids).toEqual([92])
  })
}
