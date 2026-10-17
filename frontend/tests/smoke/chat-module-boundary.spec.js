import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const frontendRoot = path.resolve(process.cwd())

test('ChatView delegates attachment handling and stays below the frozen cap', () => {
  const chatView = fs.readFileSync(
    path.join(frontendRoot, 'src/components/business/ChatView.vue'),
    'utf8',
  )
  const attachmentComposable = path.join(
    frontendRoot,
    'src/composables/useChatAttachments.js',
  )
  const thinkingComposable = path.join(
    frontendRoot,
    'src/composables/useThinkingTimer.js',
  )

  expect(fs.existsSync(attachmentComposable)).toBe(true)
  expect(fs.existsSync(thinkingComposable)).toBe(true)
  expect(chatView).toContain('useChatAttachments')
  expect(chatView).toContain('useThinkingTimer')
  expect(chatView.split('\n').length).toBeLessThanOrEqual(1609)
})
