import test from 'node:test'
import assert from 'node:assert/strict'
import { validateUrl } from '../../src/utils/validate.js'

test('rejects damaged Markdown links before upload', () => {
  for (const url of [
    'https://test.invalid/post](https://test.invalid/post',
    '[原帖](https://test.invalid/post)',
    'https://',
    'https:///post',
    'https://user:secret@test.invalid/post',
  ]) assert.equal(validateUrl(url).valid, false, url)
})

test('preserves plain links, Unicode and valid parentheses', () => {
  for (const url of ['', 'https://test.invalid/中文面经', 'https://test.invalid/article_(one)?x=1&y=2#top']) {
    assert.deepEqual(validateUrl(url), { valid: true, value: url })
  }
})
