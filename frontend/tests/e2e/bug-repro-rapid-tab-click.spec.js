/**
 * Bug Reproduction: Rapid clicking on 高频题库 tab causes other tabs to show empty content
 * 
 * Steps to reproduce:
 * 1. Login to the app
 * 2. Click on 高频题库 (MasterBank) tab multiple times rapidly
 * 3. Try to open 模拟面试 (Chat), 知识图谱 (KnowledgeGraph) tabs
 * 4. Observe that these tabs show empty content
 */
import { test, expect } from '@playwright/test'

const BASE_URL = 'http://localhost:3000'

test.describe('Bug Reproduction: Rapid Tab Clicking', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to the app
    await page.goto(BASE_URL)
    await page.waitForLoadState('networkidle')
    
    // Login with test credentials
    await page.fill('input[placeholder*="用户名"]', 'sj')
    await page.fill('input[placeholder*="密码"]', 'qnmlgb233..')
    await page.click('button:has-text("登录")')
    
    // Wait for login to complete and main content to load
    await page.waitForSelector('text=高频题库', { timeout: 10000 })
    await page.waitForTimeout(1000) // Extra wait for full initialization
  })

  test('Reproduce bug: rapid clicking on 高频题库 breaks other tabs', async ({ page }) => {
    console.log('Step 1: Taking initial screenshot...')
    await page.screenshot({ path: '/tmp/bug-repro-01-initial.png', fullPage: true })
    
    // Find the 高频题库 tab
    const masterBankTab = page.locator('button:has-text("高频题库")')
    await expect(masterBankTab).toBeVisible()
    
    console.log('Step 2: Rapidly clicking 高频题库 tab 15 times...')
    for (let i = 0; i < 15; i++) {
      await masterBankTab.click({ delay: 50 }) // Fast clicks with 50ms delay
      console.log(`  Click ${i + 1}/15`)
    }
    
    // Wait a bit after rapid clicking
    await page.waitForTimeout(500)
    
    console.log('Step 3: Taking screenshot after rapid clicks...')
    await page.screenshot({ path: '/tmp/bug-repro-02-after-rapid-clicks.png', fullPage: true })
    
    // Now try to open other tabs and check if they show content
    const tabsToTest = [
      { name: '模拟面试', key: 'Chat' },
      { name: '知识图谱', key: 'KnowledgeGraph' }
    ]
    
    for (const tab of tabsToTest) {
      console.log(`\nStep 4: Testing ${tab.name} tab...`)
      
      // Click on the tab
      const tabButton = page.locator(`button:has-text("${tab.name}")`)
      await expect(tabButton).toBeVisible()
      await tabButton.click()
      
      // Wait for tab to load
      await page.waitForTimeout(1500)
      
      // Take screenshot
      await page.screenshot({ 
        path: `/tmp/bug-repro-03-${tab.key}-tab.png`, 
        fullPage: true 
      })
      
      // Check if the tab content is empty
      // Look for the main content area (the tab content div)
      const contentArea = page.locator('.tab-content')
      await expect(contentArea).toBeVisible()
      
      // Check for loading indicators or empty states
      const hasLoadingSpinner = await page.locator('.animate-spin').count() > 0
      const hasEmptyState = await page.locator('text=暂无数据').count() > 0
      const hasContent = await page.locator('.card-smooth, .question-card, .chat-message').count() > 0
      
      console.log(`  ${tab.name} tab analysis:`)
      console.log(`    - Has loading spinner: ${hasLoadingSpinner}`)
      console.log(`    - Has empty state: ${hasEmptyState}`)
      console.log(`    - Has content: ${hasContent}`)
      
      // Check for JavaScript errors in console
      const errors = []
      page.on('console', msg => {
        if (msg.type() === 'error') {
          errors.push(msg.text())
        }
      })
      
      if (errors.length > 0) {
        console.log(`    - Console errors: ${errors.join(', ')}`)
      }
    }
    
    console.log('\nStep 5: Taking final screenshot...')
    await page.screenshot({ path: '/tmp/bug-repro-04-final.png', fullPage: true })
    
    // Verify the bug exists - at least one of the tabs should show empty content
    // This test will help us identify the issue
    console.log('\n✅ Bug reproduction test completed. Check /tmp/bug-repro-*.png for screenshots.')
  })

  test('Check for race conditions in tab switching', async ({ page }) => {
    console.log('Testing for race conditions...')
    
    // Monitor network requests
    const requests = []
    page.on('request', request => {
      if (request.url().includes('/api/')) {
        requests.push({
          url: request.url(),
          method: request.method(),
          timestamp: Date.now()
        })
      }
    })
    
    // Monitor console errors
    const errors = []
    page.on('console', msg => {
      if (msg.type() === 'error') {
        errors.push(msg.text())
      }
    })
    
    // Rapidly switch between tabs
    const tabSequence = ['高频题库', '模拟面试', '知识图谱', '高频题库', '模拟面试']
    
    for (const tabName of tabSequence) {
      const tab = page.locator(`button:has-text("${tabName}")`)
      await tab.click({ delay: 100 })
      await page.waitForTimeout(200)
    }
    
    // Check for errors
    console.log(`\nNetwork requests made: ${requests.length}`)
    console.log(`Console errors: ${errors.length}`)
    
    if (errors.length > 0) {
      console.log('\nConsole errors detected:')
      errors.forEach((error, i) => {
        console.log(`  ${i + 1}. ${error}`)
      })
    }
    
    // Take final screenshot
    await page.screenshot({ path: '/tmp/bug-repro-05-race-condition.png', fullPage: true })
  })
})
