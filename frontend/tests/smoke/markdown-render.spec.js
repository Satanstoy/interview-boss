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
  expect(html).toContain('class="answer-source-link"')
  expect(html).toContain('class="answer-source-favicon"')
  expect(html).toContain('https://www.google.com/s2/favicons?domain=example.com')
  expect(html).toContain('class="answer-source-label">官方文档</span>')
  expect(html).toContain('target="_blank"')
  expect(html).toContain('rel="noopener noreferrer"')
  expect(html).not.toContain('<script>')
})
