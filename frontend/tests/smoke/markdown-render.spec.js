import { expect, test } from '@playwright/test'

test('markdown renderer keeps structure, highlighting, links, and sanitization', async ({ page }) => {
  await page.goto('/login')

  const html = await page.evaluate(async () => {
    const { renderSafeMarkdown } = await import('/src/utils/markdown.js')
    return renderSafeMarkdown([
      '### 一句话记忆',
      '',
      '- **重点**：先查缓存，再查数据库。',
      '',
      '| 方案 | 取舍 |',
      '| --- | --- |',
      '| Redis | 快 |',
      '',
      '```python',
      'print("ok")',
      '```',
      '',
      '[官方文档](https://example.com)',
      '<script>alert("xss")</script>',
    ].join('\n'))
  })

  expect(html).toContain('<h3>一句话记忆</h3>')
  expect(html).toContain('class="table-wrapper"')
  expect(html).toContain('language-python')
  expect(html).toContain('href="https://example.com"')
  expect(html).not.toContain('<script>')
})
