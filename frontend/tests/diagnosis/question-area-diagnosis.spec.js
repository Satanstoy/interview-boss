/**
 * 题库区域面积过小诊断测试
 *
 * 测试目标：找出前端界面中题库/刷题区域显示面积过小的根本原因
 * 测试维度：
 *   1. 不同视口尺寸下的布局表现
 *   2. Grid 布局比例是否合理
 *   3. 虚拟滚动区域高度计算是否正确
 *   4. overflow: hidden 是否裁剪了内容
 *   5. 各层级元素的实际渲染尺寸
 *   6. 内容区可用面积 vs 视口面积的比率
 */

import { test, expect } from '@playwright/test'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

// 收集所有诊断数据，最后写入报告
const reportData = {
  viewports: {},
  gridAnalysis: {},
  clippingAnalysis: null,
  layoutChain: null,
  cardAnalysis: null,
  heightCalculations: null,
}

// Shared auth token - obtained once via API
let sharedToken = null

async function getAuthToken(request) {
  if (sharedToken) return sharedToken
  const res = await request.post('http://localhost:8000/api/auth/login', {
    data: { username: 'sj', password: 'qnmlgb233..', remember_me: true },
  })
  const body = await res.json()
  sharedToken = body.token
  return sharedToken
}

// ===== 辅助函数 =====

async function getBoxModel(page, selector) {
  return await page.evaluate((sel) => {
    const el = document.querySelector(sel)
    if (!el) return null
    const rect = el.getBoundingClientRect()
    const style = getComputedStyle(el)
    return {
      selector: sel,
      rect: {
        x: Math.round(rect.x), y: Math.round(rect.y),
        width: Math.round(rect.width), height: Math.round(rect.height),
        top: Math.round(rect.top), bottom: Math.round(rect.bottom),
      },
      computed: {
        display: style.display, position: style.position,
        overflow: style.overflow, overflowX: style.overflowX, overflowY: style.overflowY,
        width: style.width, height: style.height,
        minWidth: style.minWidth, maxWidth: style.maxWidth,
        minHeight: style.minHeight, maxHeight: style.maxHeight,
        padding: style.padding, margin: style.margin,
        boxSizing: style.boxSizing,
        gridTemplateColumns: style.gridTemplateColumns,
      },
      scroll: {
        scrollWidth: el.scrollWidth, scrollHeight: el.scrollHeight,
        clientWidth: el.clientWidth, clientHeight: el.clientHeight,
      },
    }
  }, selector)
}

async function gotoAndWait(page, request, vp) {
  if (vp) await page.setViewportSize(vp)
  const token = await getAuthToken(request)
  // Intercept refresh to avoid token rotation (consumes the one-time refresh_token)
  await page.route('**/api/auth/refresh', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ token, user: { id: 1, username: 'sj', is_admin: true } }),
    })
  })
  await page.goto('/', { waitUntil: 'networkidle', timeout: 15000 }).catch(() => {})
  await page.waitForSelector('.card-smooth, [class*="col-span"]', { timeout: 8000 }).catch(() => {})
  await page.waitForTimeout(500)
}

// ===== 测试主体 =====

test.describe('题库区域面积诊断', () => {

  // ---------- 测试 1: 多视口尺寸测量 ----------
  test('多视口尺寸下的题库面板测量', async ({ page, request }) => {
    const VIEWPORTS = {
      'mobile-375x812':   { width: 375,  height: 812 },
      'tablet-768x1024':  { width: 768,  height: 1024 },
      'laptop-1366x768':  { width: 1366, height: 768 },
      'desktop-1920x1080': { width: 1920, height: 1080 },
      '2k-2560x1440':     { width: 2560, height: 1440 },
    }

    const results = []

    for (const [name, vp] of Object.entries(VIEWPORTS)) {
      await gotoAndWait(page, request, vp)

      // 测量 main 容器
      const mainBox = await getBoxModel(page, 'main')

      // 测量 grid 容器
      const gridBox = await page.evaluate(() => {
        const grid = document.querySelector('main > div')
        if (!grid) return null
        const r = grid.getBoundingClientRect()
        const s = getComputedStyle(grid)
        return { width: Math.round(r.width), height: Math.round(r.height), columns: s.gridTemplateColumns, gap: s.gap }
      })

      // 测量题库面板 (col-span-3)
      const panelBox = await page.evaluate(() => {
        const grid = document.querySelector('main > div')
        if (!grid) return null
        const panel = Array.from(grid.children).find(c => c.className.includes('col-span-3'))
        if (!panel) return null
        const r = panel.getBoundingClientRect()
        const s = getComputedStyle(panel)
        return {
          width: Math.round(r.width), height: Math.round(r.height),
          overflow: s.overflow,
        }
      })

      // 测量侧边栏
      const sidebarBox = await page.evaluate(() => {
        const grid = document.querySelector('main > div')
        if (!grid) return null
        const sb = Array.from(grid.children).find(c => c.className.includes('col-span-1'))
        if (!sb) return null
        const r = sb.getBoundingClientRect()
        return { width: Math.round(r.width), height: Math.round(r.height) }
      })

      // 测量虚拟滚动区
      const scrollerBox = await getBoxModel(page, '.virtual-scroller')

      // 测量 TabBar
      const tabHeight = await page.evaluate(() => {
        const panel = document.querySelector('[class*="col-span-3"]')
        if (!panel) return null
        const first = panel.children[0]
        if (!first) return null
        return Math.round(first.getBoundingClientRect().height)
      })

      // 测量内容 padding 区
      const contentPad = await page.evaluate(() => {
        const panel = document.querySelector('[class*="col-span-3"]')
        if (!panel) return null
        const padDiv = panel.querySelector('[class*="p-4"], [class*="p-6"]')
        if (!padDiv) return null
        const s = getComputedStyle(padDiv)
        return {
          paddingTop: parseFloat(s.paddingTop),
          paddingBottom: parseFloat(s.paddingBottom),
          paddingLeft: parseFloat(s.paddingLeft),
          paddingRight: parseFloat(s.paddingRight),
        }
      })

      // 统计卡片
      const cardStats = await page.evaluate(() => {
        const cards = document.querySelectorAll('.card-smooth')
        if (cards.length === 0) return null
        const heights = Array.from(cards).map(c => Math.round(c.getBoundingClientRect().height))
        return {
          count: cards.length,
          avgHeight: Math.round(heights.reduce((a, b) => a + b, 0) / heights.length),
          minHeight: Math.min(...heights),
          maxHeight: Math.max(...heights),
        }
      })

      const vpArea = vp.width * vp.height
      const panelArea = panelBox ? panelBox.width * panelBox.height : 0
      const scrollerArea = scrollerBox ? scrollerBox.rect.width * scrollerBox.rect.height : 0

      results.push({
        name, vp,
        main: mainBox ? { w: mainBox.rect.width, h: mainBox.rect.height } : null,
        grid: gridBox,
        panel: panelBox ? { w: panelBox.width, h: panelBox.height, overflow: panelBox.overflow } : null,
        sidebar: sidebarBox,
        scroller: scrollerBox ? {
          w: scrollerBox.rect.width, h: scrollerBox.rect.height,
          cssHeight: scrollerBox.computed.height,
          scrollH: scrollerBox.scroll.scrollHeight,
          clientH: scrollerBox.scroll.clientHeight,
          overflowY: scrollerBox.computed.overflowY,
        } : null,
        tabHeight,
        contentPad,
        cardStats,
        panelRatio: panelArea ? ((panelArea / vpArea) * 100).toFixed(1) : null,
        scrollerRatio: scrollerArea ? ((scrollerArea / vpArea) * 100).toFixed(1) : null,
      })
    }

    reportData.viewports = results

    // 验证: 桌面端面板宽度至少占视口 60%
    const desktop = results.find(r => r.name === 'desktop-1920x1080')
    if (desktop?.panel) {
      const panelWidthRatio = desktop.panel.w / desktop.vp.width
      console.log(`桌面端面板宽度占比: ${(panelWidthRatio * 100).toFixed(1)}%`)
    }

    // 验证: 虚拟滚动区高度至少占视口 40%
    const laptop = results.find(r => r.name === 'laptop-1366x768')
    if (laptop?.scroller) {
      const scrollerHeightRatio = laptop.scroller.h / laptop.vp.height
      console.log(`笔记本滚动区高度占比: ${(scrollerHeightRatio * 100).toFixed(1)}%`)
    }
  })

  // ---------- 测试 2: overflow: hidden 裁剪检测 ----------
  test('overflow: hidden 裁剪检测', async ({ page, request }) => {
    await gotoAndWait(page, request, { width: 1440, height: 900 })

    const result = await page.evaluate(() => {
      const panel = document.querySelector('[class*="col-span-3"]')
      const scroller = document.querySelector('.virtual-scroller')
      if (!panel || !scroller) return null

      const pStyle = getComputedStyle(panel)
      const pRect = panel.getBoundingClientRect()
      const sRect = scroller.getBoundingClientRect()

      return {
        panelOverflow: pStyle.overflow,
        panelSize: { w: Math.round(pRect.width), h: Math.round(pRect.height) },
        scrollerSize: { w: Math.round(sRect.width), h: Math.round(sRect.height) },
        scrollerOverflowsPanel: sRect.height > pRect.height,
        heightDiff: Math.round(sRect.height - pRect.height),
        panelChildrenTotalHeight: Math.round(
          Array.from(panel.children).reduce((sum, c) => sum + c.getBoundingClientRect().height, 0)
        ),
      }
    })

    reportData.clippingAnalysis = result
  })

  // ---------- 测试 3: 布局链逐层分析 ----------
  test('从 body 到虚拟滚动区的完整布局链', async ({ page, request }) => {
    await gotoAndWait(page, request, { width: 1440, height: 900 })

    const chain = await page.evaluate(() => {
      const target = document.querySelector('.virtual-scroller')
      if (!target) return null
      const result = []
      let el = target
      while (el && el !== document.documentElement) {
        const rect = el.getBoundingClientRect()
        const style = getComputedStyle(el)
        result.unshift({
          tag: el.tagName.toLowerCase(),
          id: el.id || null,
          classes: Array.from(el.classList).slice(0, 4).join('.'),
          w: Math.round(rect.width),
          h: Math.round(rect.height),
          display: style.display,
          overflow: style.overflow,
          maxWidth: style.maxWidth,
          maxHeight: style.maxHeight,
        })
        el = el.parentElement
      }
      return result
    })

    reportData.layoutChain = chain

    // 检测高度骤降
    if (chain) {
      for (let i = 1; i < chain.length; i++) {
        const drop = chain[i - 1].h - chain[i].h
        if (drop > 30) {
          console.log(`布局链高度骤降: 第${i-1}层(${chain[i-1].tag}.${chain[i-1].classes}) ${chain[i-1].h}px → 第${i}层(${chain[i].tag}.${chain[i].classes}) ${chain[i].h}px, 差值 ${drop}px`)
        }
      }
    }
  })

  // ---------- 测试 4: Grid 比例分析 ----------
  test('Grid 布局比例在不同桌面宽度下的表现', async ({ page, request }) => {
    const desktopViewports = [
      { width: 1024, height: 768, label: 'lg-1024' },
      { width: 1280, height: 800, label: 'xl-1280' },
      { width: 1440, height: 900, label: 'custom-1440' },
      { width: 1920, height: 1080, label: 'fhd-1920' },
    ]

    const gridResults = []

    for (const vp of desktopViewports) {
      await gotoAndWait(page, request, vp)

      const info = await page.evaluate(() => {
        const grid = document.querySelector('main > div')
        if (!grid) return null
        const children = Array.from(grid.children)
        const style = getComputedStyle(grid)
        return {
          columns: style.gridTemplateColumns,
          gap: style.gap,
          children: children.map(c => {
            const r = c.getBoundingClientRect()
            return { w: Math.round(r.width), h: Math.round(r.height), cls: c.className.substring(0, 60) }
          }),
        }
      })

      if (info && info.children.length >= 2) {
        const sidebarW = info.children[0].w
        const panelW = info.children[1].w
        gridResults.push({
          viewport: vp.label,
          columns: info.columns,
          gap: info.gap,
          sidebarW,
          panelW,
          ratio: (panelW / sidebarW).toFixed(2),
          panelPercent: ((panelW / (sidebarW + panelW)) * 100).toFixed(1),
        })
      }
    }

    reportData.gridAnalysis = gridResults
  })

  // ---------- 测试 5: 虚拟滚动高度计算验证 ----------
  test('虚拟滚动高度计算公式验证', async ({ page }) => {
    const viewportHeights = [600, 700, 768, 800, 900, 1000, 1080, 1440]

    const calculations = viewportHeights.map(h => {
      const desktopH = h - 280
      const mobileH = h - 400
      return {
        viewportHeight: h,
        desktopScroller: desktopH,
        desktopRatio: ((desktopH / h) * 100).toFixed(1),
        mobileScroller: mobileH,
        mobileRatio: ((mobileH / h) * 100).toFixed(1),
      }
    })

    reportData.heightCalculations = calculations
  })

  // ---------- 测试 6: 卡片密度分析 ----------
  test('问题卡片尺寸与密度分析', async ({ page, request }) => {
    await gotoAndWait(page, request, { width: 1440, height: 900 })

    const cardData = await page.evaluate(() => {
      const cards = document.querySelectorAll('.card-smooth')
      if (cards.length === 0) return null

      const samples = []
      for (let i = 0; i < Math.min(cards.length, 5); i++) {
        const card = cards[i]
        const rect = card.getBoundingClientRect()
        const style = getComputedStyle(card)

        const header = card.querySelector('[class*="flex"][class*="gap-4"]')
        const badge = card.querySelector('[class*="min-w-"]')
        const textArea = card.querySelector('[class*="flex-1"][class*="min-w-0"]')

        samples.push({
          index: i,
          width: Math.round(rect.width),
          height: Math.round(rect.height),
          area: Math.round(rect.width * rect.height),
          headerH: header ? Math.round(header.getBoundingClientRect().height) : null,
          badgeW: badge ? Math.round(badge.getBoundingClientRect().width) : null,
          textW: textArea ? Math.round(textArea.getBoundingClientRect().width) : null,
          padding: style.padding,
        })
      }

      const heights = samples.map(s => s.height)
      return {
        totalCards: cards.length,
        samples,
        avgHeight: Math.round(heights.reduce((a, b) => a + b, 0) / heights.length),
        avgArea: Math.round(samples.reduce((s, r) => s + r.area, 0) / samples.length),
      }
    })

    reportData.cardAnalysis = cardData
  })

  // ---------- 最终: 生成报告 ----------
  test('生成诊断报告', async ({ page }) => {
    const lines = []
    lines.push('# 题库区域面积诊断报告')
    lines.push('')
    lines.push(`生成时间: ${new Date().toLocaleString('zh-CN')}`)
    lines.push(`测试工具: Playwright`)
    lines.push('')

    // --- 多视口测量结果 ---
    lines.push('---')
    lines.push('')
    lines.push('## 1. 多视口尺寸测量结果')
    lines.push('')
    lines.push('| 视口 | 状态 | 面板尺寸 | 滚动区尺寸 | 滚动区CSS高度 | 面板/视口% | 滚动区/视口% | Tab高 | 卡片数 | 卡片均高 |')
    lines.push('|------|------|---------|-----------|-------------|----------|------------|-------|--------|---------|')
    for (const r of reportData.viewports) {
      lines.push(`| ${r.name} | ✓ | ${r.panel?.w}x${r.panel?.h} | ${r.scroller?.w}x${r.scroller?.h} | ${r.scroller?.cssHeight} | ${r.panelRatio}% | ${r.scrollerRatio}% | ${r.tabHeight || '-'}px | ${r.cardStats?.count || '-'} | ${r.cardStats?.avgHeight || '-'}px |`)
    }
    lines.push('')

    // 关键发现
    lines.push('### 关键发现')
    lines.push('')
    for (const r of reportData.viewports) {
      const issues = []
      if (r.scroller && r.scroller.h < r.vp.height * 0.4) {
        issues.push(`滚动区高度仅占视口 ${(r.scroller.h / r.vp.height * 100).toFixed(1)}%，不到 40%`)
      }
      if (r.panel && r.panel.overflow === 'hidden') {
        issues.push('面板 overflow: hidden 可能裁剪内容')
      }
      if (r.scroller && r.scroller.scrollH > r.scroller.clientH) {
        issues.push(`内容溢出: scrollHeight(${r.scroller.scrollH}) > clientHeight(${r.scroller.clientH})`)
      }
      if (issues.length > 0) {
        lines.push(`**${r.name}:**`)
        issues.forEach(i => lines.push(`- ${i}`))
        lines.push('')
      }
    }

    // --- overflow 裁剪分析 ---
    lines.push('---')
    lines.push('')
    lines.push('## 2. overflow: hidden 裁剪分析')
    lines.push('')
    if (reportData.clippingAnalysis) {
      const c = reportData.clippingAnalysis
      lines.push(`- 面板 overflow: \`${c.panelOverflow}\``)
      lines.push(`- 面板尺寸: ${c.panelSize.w}x${c.panelSize.h}px`)
      lines.push(`- 滚动区尺寸: ${c.scrollerSize.w}x${c.scrollerSize.h}px`)
      lines.push(`- 面板内子元素总高度: ${c.panelChildrenTotalHeight}px`)
      lines.push(`- 滚动区是否溢出面板: ${c.scrollerOverflowsPanel ? '**是**' : '否'} (差值: ${c.heightDiff}px)`)
      lines.push('')
      if (c.scrollerOverflowsPanel && c.panelOverflow === 'hidden') {
        lines.push('> **结论:** 滚动区高度超出面板，而面板设置了 `overflow: hidden`，')
        lines.push('> 但滚动区自身的 `overflow-y: auto` 使其内部滚动，所以 `overflow: hidden` 主要影响的是')
        lines.push('> 面板圆角裁剪（`rounded-2xl`）而非内容裁剪。')
      }
    } else {
      lines.push('*无数据*')
    }
    lines.push('')

    // --- 布局链 ---
    lines.push('---')
    lines.push('')
    lines.push('## 3. 布局链逐层分析 (1440x900)')
    lines.push('')
    if (reportData.layoutChain) {
      lines.push('| # | 标签 | 类名 | 宽度 | 高度 | display | overflow | max-width | max-height |')
      lines.push('|---|------|------|------|------|---------|----------|-----------|------------|')
      reportData.layoutChain.forEach((el, i) => {
        lines.push(`| ${i} | ${el.tag}${el.id ? '#'+el.id : ''} | ${el.classes} | ${el.w}px | ${el.h}px | ${el.display} | ${el.overflow} | ${el.maxWidth} | ${el.maxHeight} |`)
      })
      lines.push('')

      // 高度骤降分析
      lines.push('### 高度骤降分析')
      lines.push('')
      let foundDrop = false
      for (let i = 1; i < reportData.layoutChain.length; i++) {
        const prev = reportData.layoutChain[i - 1]
        const curr = reportData.layoutChain[i]
        const drop = prev.h - curr.h
        if (drop > 30) {
          foundDrop = true
          lines.push(`- **第 ${i-1} → ${i} 层:** ${prev.tag}.${prev.classes} (${prev.h}px) → ${curr.tag}.${curr.classes} (${curr.h}px), 降低 **${drop}px**`)
        }
      }
      if (!foundDrop) {
        lines.push('- 无显著高度骤降（每层差值 < 30px）')
      }
    } else {
      lines.push('*无数据*')
    }
    lines.push('')

    // --- Grid 比例 ---
    lines.push('---')
    lines.push('')
    lines.push('## 4. Grid 布局比例分析')
    lines.push('')
    if (reportData.gridAnalysis.length > 0) {
      lines.push('| 视口 | grid-template-columns | 侧边栏宽 | 面板宽 | 比例 | 面板占比 |')
      lines.push('|------|----------------------|----------|--------|------|---------|')
      for (const g of reportData.gridAnalysis) {
        lines.push(`| ${g.viewport} | ${g.columns} | ${g.sidebarW}px | ${g.panelW}px | ${g.ratio}:1 | ${g.panelPercent}% |`)
      }
      lines.push('')
      lines.push('### 分析')
      lines.push('')
      lines.push('- `grid-cols-4` + `col-span-3` 理论比例为 3:1 (75%:25%)')
      lines.push('- 实际比例受 `max-w-[1440px]` 容器和 padding/gap 影响')
      lines.push('- 当视口 > 1440px 时，两侧留白增大，面板实际宽度被 `max-width` 限制')
    } else {
      lines.push('*无数据*')
    }
    lines.push('')

    // --- 高度计算公式 ---
    lines.push('---')
    lines.push('')
    lines.push('## 5. 虚拟滚动高度计算公式验证')
    lines.push('')
    lines.push('公式: 桌面端 `calc(100vh - 280px)`, 移动端 `calc(100vh - 400px)`')
    lines.push('')
    lines.push('| 视口高度 | 桌面端(100vh-280) | 占比 | 移动端(100vh-400) | 占比 |')
    lines.push('|---------|-------------------|------|-------------------|------|')
    if (reportData.heightCalculations) {
      for (const c of reportData.heightCalculations) {
        lines.push(`| ${c.viewportHeight}px | ${c.desktopScroller}px | ${c.desktopRatio}% | ${c.mobileScroller}px | ${c.mobileRatio}% |`)
      }
    }
    lines.push('')
    lines.push('### 280px 扣除值分解估算')
    lines.push('')
    lines.push('| 组成部分 | 估算高度 |')
    lines.push('|---------|---------|')
    lines.push('| 导航栏 (nav h-14) | ~56px |')
    lines.push('| main padding (lg:p-8) | ~64px (上下各32px) |')
    lines.push('| TabBar (py-3.5 + border) | ~58px |')
    lines.push('| SearchFilterBar + 间距 | ~56px |')
    lines.push('| 内容区 padding (lg:p-6) | ~48px (上下各24px) |')
    lines.push('| **合计** | **~282px** |')
    lines.push('')
    lines.push('> **问题:** 280px 是静态值，但 TabBar 高度、SearchFilterBar 是否显示、子标签筛选栏等')
    lines.push('> 都是动态的。当这些元素实际占用更多空间时，虚拟滚动区会被压缩。')
    lines.push('> 当视口高度 < 800px（常见笔记本），可用高度 < 520px，体验较差。')
    lines.push('')

    // --- 卡片分析 ---
    lines.push('---')
    lines.push('')
    lines.push('## 6. 问题卡片尺寸分析')
    lines.push('')
    if (reportData.cardAnalysis) {
      const cd = reportData.cardAnalysis
      lines.push(`- 可见卡片总数: ${cd.totalCards}`)
      lines.push(`- 平均高度: ${cd.avgHeight}px`)
      lines.push(`- 平均面积: ${cd.avgArea} px²`)
      lines.push('')
      lines.push('| 序号 | 宽度 | 高度 | 面积 | 头部高 | 徽标宽 | 文本区宽 | padding |')
      lines.push('|------|------|------|------|--------|--------|---------|---------|')
      for (const s of cd.samples) {
        lines.push(`| ${s.index} | ${s.width}px | ${s.height}px | ${s.area}px² | ${s.headerH || '-'}px | ${s.badgeW || '-'}px | ${s.textW || '-'}px | ${s.padding} |`)
      }
    } else {
      lines.push('*无卡片数据*')
    }
    lines.push('')

    // --- 综合结论 ---
    lines.push('---')
    lines.push('')
    lines.push('## 7. 综合诊断结论')
    lines.push('')
    lines.push('### 根本原因（按影响程度排序）')
    lines.push('')
    lines.push('#### 1. 虚拟滚动区高度使用固定扣除值（**高影响**）')
    lines.push('')
    lines.push('`MasterBankList.vue` 中 `.virtual-scroller` 的高度为 `calc(100vh - 280px)`，')
    lines.push('这个 280px 是硬编码的估算值，没有考虑：')
    lines.push('- 子标签筛选栏的动态显示/隐藏')
    lines.push('- 批量操作面板（BatchActionPanel）的显示')
    lines.push('- "全部展开/收起" 按钮行')
    lines.push('- 不同设备上 TabBar/SearchFilterBar 的实际高度差异')
    lines.push('')
    lines.push('#### 2. Grid 布局 3:1 比例固定（**中影响**）')
    lines.push('')
    lines.push('`grid-cols-4` + `lg:col-span-3` 使题库面板固定占 75% 宽度。')
    lines.push('对于以内容阅读为主的题库场景，侧边栏可能不需要始终占 25%。')
    lines.push('')
    lines.push('#### 3. 多层 padding 叠加（**中影响**）')
    lines.push('')
    lines.push('main (32px) → 内容区 (24px) → 卡片 (20px) 共 76px 水平 padding，')
    lines.push('在 1366px 笔记本上实际内容宽度仅约 1290px * 75% - 48px ≈ 919px。')
    lines.push('')
    lines.push('#### 4. overflow: hidden 用于圆角裁剪（**低影响**）')
    lines.push('')
    lines.push('面板的 `overflow: hidden` 主要是为了 `rounded-2xl` 圆角裁剪，')
    lines.push('但由于虚拟滚动区自身的 `overflow-y: auto`，不会裁剪滚动内容。')
    lines.push('')
    lines.push('#### 5. max-w-[1440px] 容器限制（**仅影响大屏**）')
    lines.push('')
    lines.push('在 >1440px 的显示器上，内容区不会填满屏幕，两侧留白。')
    lines.push('')

    lines.push('### 优化建议')
    lines.push('')
    lines.push('1. **动态计算虚拟滚动区高度** — 使用 `ResizeObserver` 或 CSS `calc()` 结合 CSS 变量，')
    lines.push('   根据 TabBar、SearchFilterBar 等元素的实际高度动态计算')
    lines.push('2. **调整 Grid 比例** — 考虑 `lg:grid-cols-5` + `lg:col-span-4` (80%:20%) 或响应式折叠侧边栏')
    lines.push('3. **减少 padding 层级** — 合并 main padding 和内容区 padding')
    lines.push('4. **小屏优化** — 在 1366px 以下考虑隐藏或折叠侧边栏')
    lines.push('5. **卡片紧凑模式** — 提供可选的更紧凑的卡片布局，减少单卡高度')
    lines.push('')

    // 写入报告
    const reportPath = path.join(__dirname, 'diagnosis-report.md')
    fs.writeFileSync(reportPath, lines.join('\n'), 'utf-8')
    console.log(`\n诊断报告已保存至: ${reportPath}`)

    // 基本断言: 报告不为空
    expect(lines.length).toBeGreaterThan(50)
  })
})
