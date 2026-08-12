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
  expect(html).toContain('data-material="glass"')
  expect(html).toContain('class="answer-source-preview rounded-lg')
  expect(html).toContain('class="answer-source-preview__favicon"')
  expect(html).toContain('class="answer-source-favicon"')
  expect(html).toContain('https://www.google.com/s2/favicons?domain=example.com')
  expect(html).toContain('class="answer-source-label">官方文档</span>')
  expect(html).toContain('target="_blank"')
  expect(html).toContain('rel="noopener noreferrer"')
  expect(html).not.toContain('<script>')

  await page.evaluate((renderedHtml) => {
    const host = document.createElement('div')
    host.id = 'inline-citation-smoke'
    host.className = 'answer-content'
    host.innerHTML = renderedHtml
    document.body.appendChild(host)
  }, html)

  const citation = page.locator('#inline-citation-smoke .answer-source-link')
  const preview = citation.locator('.answer-source-preview')
  const citationMetrics = await citation.evaluate((element) => {
    const style = getComputedStyle(element)
    const parentStyle = getComputedStyle(element.parentElement)
    return {
      height: element.getBoundingClientRect().height,
      lineHeight: Number.parseFloat(parentStyle.lineHeight),
      boxShadow: style.boxShadow,
      tooltipSurface: element.querySelector('.answer-source-preview')?.getAttribute('data-slot') || '',
    }
  })
  expect(citationMetrics.height).toBeLessThanOrEqual(citationMetrics.lineHeight + 1)
  expect(citationMetrics.boxShadow).toBe('none')
  expect(citationMetrics.tooltipSurface).toBe('tooltip-content')
  await expect(citation).not.toHaveCSS('color', 'rgba(0, 0, 0, 0)')
  await expect(preview).toHaveCSS('opacity', '0')
  await citation.hover()
  await expect(preview).toHaveCSS('opacity', '1')
})
