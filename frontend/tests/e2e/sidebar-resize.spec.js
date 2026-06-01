import { test, expect } from '@playwright/test'

test.describe('Sidebar resize handle', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    // Wait for login to complete (auth state from setup) and main content to load
    await page.waitForSelector('main', { timeout: 15000 })
    // Wait a bit more for Vue to fully render
    await page.waitForTimeout(1000)
  })

  test('resize handle is visible on desktop', async ({ page }) => {
    const handle = page.locator('.resize-handle')
    await expect(handle).toBeVisible({ timeout: 5000 })
  })

  test('resize handle grip appears on hover', async ({ page }) => {
    const handle = page.locator('.resize-handle')
    const grip = page.locator('.resize-handle__grip')

    await expect(handle).toBeVisible({ timeout: 5000 })

    // Hover over handle
    await handle.hover()
    await page.waitForTimeout(200)

    // Grip should become visible (opacity 1 on hover)
    const opacity = await grip.evaluate(el => getComputedStyle(el).opacity)
    expect(parseFloat(opacity)).toBeGreaterThan(0)
  })

  test('drag handle to resize sidebar wider', async ({ page }) => {
    const handle = page.locator('.resize-handle')
    const wrapper = page.locator('.sidebar-wrapper')

    await expect(handle).toBeVisible({ timeout: 5000 })

    // Get initial sidebar width
    const initialWidth = await wrapper.evaluate(el => el.getBoundingClientRect().width)

    // Drag handle to the right by 100px
    const handleBox = await handle.boundingBox()
    const startX = handleBox.x + handleBox.width / 2
    const startY = handleBox.y + handleBox.height / 2

    await page.mouse.move(startX, startY)
    await page.mouse.down()
    await page.mouse.move(startX + 100, startY, { steps: 5 })
    await page.mouse.up()

    // Wait for transition
    await page.waitForTimeout(300)

    // Sidebar should be wider
    const newWidth = await wrapper.evaluate(el => el.getBoundingClientRect().width)
    expect(newWidth).toBeGreaterThan(initialWidth)
  })

  test('drag handle to resize sidebar narrower', async ({ page }) => {
    const handle = page.locator('.resize-handle')
    const wrapper = page.locator('.sidebar-wrapper')

    await expect(handle).toBeVisible({ timeout: 5000 })

    // Get initial sidebar width
    const initialWidth = await wrapper.evaluate(el => el.getBoundingClientRect().width)

    // Drag handle to the left by 80px
    const handleBox = await handle.boundingBox()
    const startX = handleBox.x + handleBox.width / 2
    const startY = handleBox.y + handleBox.height / 2

    await page.mouse.move(startX, startY)
    await page.mouse.down()
    await page.mouse.move(startX - 80, startY, { steps: 5 })
    await page.mouse.up()

    // Wait for transition
    await page.waitForTimeout(300)

    // Sidebar should be narrower
    const newWidth = await wrapper.evaluate(el => el.getBoundingClientRect().width)
    expect(newWidth).toBeLessThan(initialWidth)
  })

  test('drag handle far left collapses sidebar', async ({ page }) => {
    const handle = page.locator('.resize-handle')
    const wrapper = page.locator('.sidebar-wrapper')

    await expect(handle).toBeVisible({ timeout: 5000 })

    // Drag handle far to the left (past collapse threshold)
    const handleBox = await handle.boundingBox()
    const startX = handleBox.x + handleBox.width / 2
    const startY = handleBox.y + handleBox.height / 2

    await page.mouse.move(startX, startY)
    await page.mouse.down()
    await page.mouse.move(startX - 400, startY, { steps: 10 })
    await page.mouse.up()

    // Wait for transition
    await page.waitForTimeout(300)

    // Sidebar should be collapsed (width ~0)
    const wrapperWidth = await wrapper.evaluate(el => el.getBoundingClientRect().width)
    expect(wrapperWidth).toBeLessThan(10)
  })

  test('resize handle is visible when sidebar is collapsed', async ({ page }) => {
    const handle = page.locator('.resize-handle')
    const wrapper = page.locator('.sidebar-wrapper')

    await expect(handle).toBeVisible({ timeout: 5000 })

    // First collapse the sidebar by dragging
    const handleBox = await handle.boundingBox()
    const startX = handleBox.x + handleBox.width / 2
    const startY = handleBox.y + handleBox.height / 2

    await page.mouse.move(startX, startY)
    await page.mouse.down()
    await page.mouse.move(startX - 400, startY, { steps: 10 })
    await page.mouse.up()
    await page.waitForTimeout(300)

    // Handle should still be visible even when collapsed
    await expect(handle).toBeVisible()

    // Handle should have the collapsed class
    await expect(handle).toHaveClass(/resize-handle--collapsed/)
  })

  test('drag from collapsed state expands sidebar', async ({ page }) => {
    const handle = page.locator('.resize-handle')
    const wrapper = page.locator('.sidebar-wrapper')

    await expect(handle).toBeVisible({ timeout: 5000 })

    // First collapse the sidebar
    let handleBox = await handle.boundingBox()
    let startX = handleBox.x + handleBox.width / 2
    let startY = handleBox.y + handleBox.height / 2

    await page.mouse.move(startX, startY)
    await page.mouse.down()
    await page.mouse.move(startX - 400, startY, { steps: 10 })
    await page.mouse.up()
    await page.waitForTimeout(300)

    // Now drag from collapsed state to expand
    handleBox = await handle.boundingBox()
    startX = handleBox.x + handleBox.width / 2
    startY = handleBox.y + handleBox.height / 2

    await page.mouse.move(startX, startY)
    await page.mouse.down()
    await page.mouse.move(startX + 300, startY, { steps: 10 })
    await page.mouse.up()
    await page.waitForTimeout(300)

    // Sidebar should be expanded
    const wrapperWidth = await wrapper.evaluate(el => el.getBoundingClientRect().width)
    expect(wrapperWidth).toBeGreaterThan(100)
  })

  test('sidebar width is persisted to localStorage', async ({ page }) => {
    const handle = page.locator('.resize-handle')

    await expect(handle).toBeVisible({ timeout: 5000 })

    // Drag handle to resize
    const handleBox = await handle.boundingBox()
    const startX = handleBox.x + handleBox.width / 2
    const startY = handleBox.y + handleBox.height / 2

    await page.mouse.move(startX, startY)
    await page.mouse.down()
    await page.mouse.move(startX + 50, startY, { steps: 5 })
    await page.mouse.up()
    await page.waitForTimeout(300)

    // Check localStorage
    const savedWidth = await page.evaluate(() => localStorage.getItem('sidebar-width'))
    expect(savedWidth).toBeTruthy()
    const width = parseInt(savedWidth)
    expect(width).toBeGreaterThan(200)
    expect(width).toBeLessThan(480)
  })

  test('sidebar respects max width constraint', async ({ page }) => {
    const handle = page.locator('.resize-handle')
    const wrapper = page.locator('.sidebar-wrapper')

    await expect(handle).toBeVisible({ timeout: 5000 })

    // Try to drag beyond max width (480px)
    const handleBox = await handle.boundingBox()
    const startX = handleBox.x + handleBox.width / 2
    const startY = handleBox.y + handleBox.height / 2

    await page.mouse.move(startX, startY)
    await page.mouse.down()
    await page.mouse.move(startX + 500, startY, { steps: 10 })
    await page.mouse.up()
    await page.waitForTimeout(300)

    // Width should be capped at 480
    const wrapperWidth = await wrapper.evaluate(el => el.getBoundingClientRect().width)
    expect(wrapperWidth).toBeLessThanOrEqual(480)
  })
})
