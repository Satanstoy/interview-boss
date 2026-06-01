/**
 * 测试辅助工具 —— 测量元素尺寸并生成诊断报告
 */

/**
 * 获取元素的完整盒模型信息
 */
export async function getBoxModel(page, selector) {
  return await page.evaluate((sel) => {
    const el = document.querySelector(sel)
    if (!el) return null
    const rect = el.getBoundingClientRect()
    const style = getComputedStyle(el)
    return {
      selector: sel,
      rect: {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        top: Math.round(rect.top),
        right: Math.round(rect.right),
        bottom: Math.round(rect.bottom),
        left: Math.round(rect.left),
      },
      computed: {
        display: style.display,
        position: style.position,
        overflow: style.overflow,
        overflowX: style.overflowX,
        overflowY: style.overflowY,
        width: style.width,
        height: style.height,
        minWidth: style.minWidth,
        maxWidth: style.maxWidth,
        minHeight: style.minHeight,
        maxHeight: style.maxHeight,
        padding: style.padding,
        margin: style.margin,
        boxSizing: style.boxSizing,
        flexBasis: style.flexBasis,
        flexGrow: style.flexGrow,
        flexShrink: style.flexShrink,
        gridTemplateColumns: style.gridTemplateColumns,
        gridTemplateRows: style.gridTemplateRows,
      },
      scroll: {
        scrollWidth: el.scrollWidth,
        scrollHeight: el.scrollHeight,
        scrollTop: el.scrollTop,
        scrollLeft: el.scrollLeft,
        clientWidth: el.clientWidth,
        clientHeight: el.clientHeight,
      },
      childrenCount: el.children.length,
    }
  }, selector)
}

/**
 * 获取元素的实际可用内容区域（排除 padding）
 */
export async function getContentArea(page, selector) {
  return await page.evaluate((sel) => {
    const el = document.querySelector(sel)
    if (!el) return null
    const style = getComputedStyle(el)
    const rect = el.getBoundingClientRect()
    const padTop = parseFloat(style.paddingTop) || 0
    const padBottom = parseFloat(style.paddingBottom) || 0
    const padLeft = parseFloat(style.paddingLeft) || 0
    const padRight = parseFloat(style.paddingRight) || 0
    return {
      outer: { width: Math.round(rect.width), height: Math.round(rect.height) },
      inner: {
        width: Math.round(rect.width - padLeft - padRight),
        height: Math.round(rect.height - padTop - padBottom),
      },
      padding: { top: padTop, bottom: padBottom, left: padLeft, right: padRight },
    }
  }, selector)
}

/**
 * 追踪某个 CSS 属性的来源（哪些样式规则参与了计算）
 */
export async function traceStyleOrigin(page, selector, property) {
  return await page.evaluate(({ sel, prop }) => {
    const el = document.querySelector(sel)
    if (!el) return null
    const val = getComputedStyle(el)[prop]
    // 获取所有匹配的样式规则
    const matched = []
    for (const sheet of document.styleSheets) {
      try {
        for (const rule of sheet.cssRules) {
          if (rule.type === CSSRule.STYLE_RULE && el.matches(rule.selectorText)) {
            if (rule.style.getPropertyValue(prop)) {
              matched.push({
                selector: rule.selectorText,
                value: rule.style.getPropertyValue(prop),
                source: sheet.href || '<inline>',
              })
            }
          }
        }
      } catch (e) {
        // cross-origin stylesheet, skip
      }
    }
    return { property: prop, computedValue: val, matchedRules: matched }
  }, { sel: selector, prop: property })
}

/**
 * 测量虚拟滚动区域中实际渲染的卡片数量和尺寸
 */
export async function measureScrollerItems(page, scrollerSelector) {
  return await page.evaluate((sel) => {
    const scroller = document.querySelector(sel)
    if (!scroller) return null
    const items = scroller.querySelectorAll('[data-index]')
    const results = []
    for (const item of items) {
      const rect = item.getBoundingClientRect()
      const idx = item.getAttribute('data-index')
      results.push({
        index: parseInt(idx),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        top: Math.round(rect.top),
        visible: rect.bottom > 0 && rect.top < window.innerHeight,
      })
    }
    return {
      scrollerHeight: Math.round(scroller.getBoundingClientRect().height),
      scrollerClientHeight: scroller.clientHeight,
      scrollerScrollHeight: scroller.scrollHeight,
      totalItems: items.length,
      visibleItems: results.filter(r => r.visible).length,
      items: results,
    }
  }, scrollerSelector)
}

/**
 * 检查元素是否被裁剪（overflow: hidden 导致内容不可见）
 */
export async function checkClipping(page, parentSelector, childSelector) {
  return await page.evaluate(({ parentSel, childSel }) => {
    const parent = document.querySelector(parentSel)
    const child = document.querySelector(childSel)
    if (!parent || !child) return null
    const pRect = parent.getBoundingClientRect()
    const cRect = child.getBoundingClientRect()
    const pStyle = getComputedStyle(parent)
    return {
      parent: { width: Math.round(pRect.width), height: Math.round(pRect.height), overflow: pStyle.overflow },
      child: { width: Math.round(cRect.width), height: Math.round(cRect.height) },
      clipped: {
        top: cRect.top < pRect.top,
        bottom: cRect.bottom > pRect.bottom,
        left: cRect.left < pRect.left,
        right: cRect.right > pRect.right,
      },
      childOverflowsParent: cRect.height > pRect.height,
    }
  }, { parentSel: parentSelector, childSel: childSelector })
}

/**
 * 获取完整的布局链信息（从 body 到目标元素的每一层）
 */
export async function getLayoutChain(page, targetSelector) {
  return await page.evaluate((sel) => {
    const target = document.querySelector(sel)
    if (!target) return null
    const chain = []
    let el = target
    while (el && el !== document.documentElement) {
      const rect = el.getBoundingClientRect()
      const style = getComputedStyle(el)
      chain.unshift({
        tag: el.tagName.toLowerCase(),
        id: el.id || null,
        classList: Array.from(el.classList).slice(0, 5),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        display: style.display,
        overflow: style.overflow,
        maxWidth: style.maxWidth,
        maxHeight: style.maxHeight,
      })
      el = el.parentElement
    }
    return chain
  }, targetSelector)
}

/**
 * 格式化诊断报告为 Markdown
 */
export function formatReport(title, viewport, measurements) {
  const lines = [`## ${title}`, ``, `**视口尺寸:** ${viewport.width} x ${viewport.height}`, `]
  for (const [name, data] of Object.entries(measurements)) {
    lines.push(`### ${name}`)
    lines.push('```json')
    lines.push(JSON.stringify(data, null, 2))
    lines.push('```')
    lines.push('')
  }
  return lines.join('\n')
}
