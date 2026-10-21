import test from 'node:test'
import assert from 'node:assert/strict'
import { configureDisposableUserModel } from '../_helpers/real-stack-model.js'

test('disposable model setup returns its access token for authenticated polling', async (context) => {
  const requests = []
  context.mock.method(globalThis, 'fetch', async (url, options) => {
    requests.push({ url, options })
    return url === '/api/auth/refresh'
      ? { ok: true, json: async () => ({ token: 'TEST_TOKEN_PLACEHOLDER' }) }
      : { status: 200 }
  })

  const token = await configureDisposableUserModel({ evaluate: (callback) => callback() })

  assert.equal(token, 'TEST_TOKEN_PLACEHOLDER')
  assert.deepEqual(requests.map(({ url }) => url), ['/api/auth/refresh', '/api/profile/llm'])
  assert.equal(requests[1].options.headers.Authorization, `Bearer ${token}`)
})

test('disposable model setup rejects a failed refresh', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => ({ ok: false, status: 401 }))

  await assert.rejects(
    configureDisposableUserModel({ evaluate: (callback) => callback() }),
    /HTTP 401/,
  )
})
