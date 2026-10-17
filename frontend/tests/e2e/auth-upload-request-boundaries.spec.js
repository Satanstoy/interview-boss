// Real browser modules; only the HTTP boundary is stubbed.
import { test, expect } from '@playwright/test'

async function openModuleHarness(page) {
  await page.route('**/__request_boundaries', route => route.fulfill({
    contentType: 'text/html', body: '<html><body>Request boundary harness</body></html>',
  }))
  await page.goto('/__request_boundaries')
}

for (const bypassCache of [false, true]) {
  test(`a late private GET cannot repopulate the next account cache (noCache=${bypassCache})`, async ({ page }) => {
    let release
    let started
    const pending = new Promise(resolve => { started = resolve })
    const gate = new Promise(resolve => { release = resolve })
    let calls = 0
    await page.route('**/api/private-boundary', async route => {
      calls++
      if (calls === 1) { started(); await gate }
      await route.fulfill({ json: { owner: calls === 1 ? 'A' : 'B' } })
    })
    await openModuleHarness(page)
    await page.evaluate(async bypass => {
      const http = await import('/src/services/http.js')
      http.setAuthToken('ACCOUNT_A')
      window.pendingPrivateRead = http.get('/api/private-boundary', { noCache: bypass })
        .then(data => ({ data }), error => ({ code: error.code }))
    }, bypassCache)
    await pending
    await page.evaluate(async () => {
      const http = await import('/src/services/http.js')
      http.setAuthToken('ACCOUNT_B')
      http.invalidateCache()
    })
    release()
    const result = await page.evaluate(async () => {
      const old = await window.pendingPrivateRead
      const http = await import('/src/services/http.js')
      return { old, current: await http.get('/api/private-boundary') }
    })
    expect(result).toEqual({ old: { code: 'AUTH_CONTEXT_CHANGED' }, current: { owner: 'B' } })
    expect(calls).toBe(2)
  })
}

test('a delayed refresh cannot restore credentials after logout', async ({ page }) => {
  let release
  let started
  const pending = new Promise(resolve => { started = resolve })
  const gate = new Promise(resolve => { release = resolve })
  await page.route('**/api/auth/refresh', async route => {
    started(); await gate
    await route.fulfill({ json: { token: 'OLD_REFRESHED_TOKEN', user: { id: 1 } } })
  })
  await openModuleHarness(page)
  await page.evaluate(async () => {
    const http = await import('/src/services/http.js')
    http.setAuthToken('ACCOUNT_A')
    window.pendingRefresh = http.refreshAuthToken()
  })
  await pending
  await page.evaluate(async () => { (await import('/src/services/http.js')).setAuthToken('') })
  release()
  expect(await page.evaluate(async () => ({
    result: await window.pendingRefresh,
    token: (await import('/src/services/http.js')).getAuthToken(),
  }))).toEqual({ result: null, token: '' })
})

test('the same account can refresh a token and finish its request', async ({ page }) => {
  let calls = 0
  await page.route('**/api/private-boundary', route => {
    calls++
    return route.fulfill(calls === 1 ? { status: 401, json: { detail: 'expired' } } : { json: { owner: 'A' } })
  })
  await page.route('**/api/auth/refresh', route => route.fulfill({ json: { token: 'REFRESHED_A', user: { id: 1 } } }))
  await openModuleHarness(page)
  expect(await page.evaluate(async () => {
    const http = await import('/src/services/http.js')
    http.setAuthToken('ACCOUNT_A')
    return http.get('/api/private-boundary')
  })).toEqual({ owner: 'A' })
  expect(calls).toBe(2)
})

test('same-account refresh preserves concurrent private requests', async ({ page }) => {
  let release
  let started
  const pending = new Promise(resolve => { started = resolve })
  const gate = new Promise(resolve => { release = resolve })
  await page.route('**/api/slow-private', async route => {
    started(); await gate
    await route.fulfill({ json: { owner: 'A' } })
  })
  let calls = 0
  await page.route('**/api/expired-private', route => {
    calls++
    return route.fulfill(calls === 1
      ? { status: 401, json: { detail: 'expired' } }
      : { json: { owner: 'A' } })
  })
  await page.route('**/api/auth/refresh', route => route.fulfill({
    json: { token: 'REFRESHED_A', user: { id: 1 } },
  }))
  await openModuleHarness(page)
  await page.evaluate(async () => {
    const http = await import('/src/services/http.js')
    http.setAuthToken('ACCOUNT_A')
    window.pendingSlow = http.get('/api/slow-private')
      .then(data => ({ data }), error => ({ code: error.code }))
  })
  await pending
  expect(await page.evaluate(async () => {
    const http = await import('/src/services/http.js')
    return http.get('/api/expired-private')
  })).toEqual({ owner: 'A' })
  release()
  expect(await page.evaluate(() => window.pendingSlow)).toEqual({ data: { owner: 'A' } })
})

for (const boundary of ['fingerprint', 'lookup']) {
  test(`account switch during upload ${boundary} prevents private submission`, async ({ page }) => {
    let creates = 0
    await page.route('**/api/submit-jobs', route => {
      creates++
      return route.fulfill({ json: { import_id: 'wrong-owner' } })
    })
    let release
    let started
    const pending = new Promise(resolve => { started = resolve })
    const gate = new Promise(resolve => { release = resolve })
    await page.route('**/api/upload-imports/by-key/**', async route => {
      if (boundary === 'lookup') { started(); await gate }
      await route.fulfill({ status: 404, json: { detail: 'not found' } })
    })
    await openModuleHarness(page)
    await page.evaluate(async boundary => {
      const http = await import('/src/services/http.js')
      const jobs = await import('/src/composables/useSubmitJobs.js')
      http.setAuthToken('ACCOUNT_A')
      jobs.setTaskUserScope('A')
      if (boundary === 'fingerprint') {
        const digest = crypto.subtle.digest.bind(crypto.subtle)
        crypto.subtle.digest = async (...args) => {
          window.digestStarted = true
          await new Promise(resolve => { window.releaseDigest = resolve })
          return digest(...args)
        }
      }
      const data = new FormData(); data.set('raw_text', 'PRIVATE_A')
      window.pendingSubmission = jobs.submitUploadWithIdempotency(data, { draftId: 'private-draft' })
        .then(() => ({ accepted: true }), error => ({ code: error.code }))
    }, boundary)
    if (boundary === 'fingerprint') await page.waitForFunction(() => window.digestStarted)
    else await pending
    await page.evaluate(async () => {
      const http = await import('/src/services/http.js')
      const jobs = await import('/src/composables/useSubmitJobs.js')
      http.setAuthToken('ACCOUNT_B')
      jobs.setTaskUserScope('B')
    })
    if (boundary === 'fingerprint') await page.evaluate(() => window.releaseDigest())
    else release()
    expect(await page.evaluate(() => window.pendingSubmission)).toEqual({ code: 'AUTH_CONTEXT_CHANGED' })
    expect(creates).toBe(0)
    expect(await page.evaluate(() => localStorage.getItem('interviewboss-submit-draft:B:private-draft:payload'))).toBeNull()
  })
}

for (const precheckFound of [true, false]) {
  test(`changed accepted draft must surface idempotency conflict (precheck=${precheckFound})`, async ({ page }) => {
    let creates = 0
    let lookups = 0
    await page.route('**/api/upload-imports/by-key/**', route => {
      lookups++
      const found = creates > 0 && (precheckFound || lookups > 2)
      return route.fulfill(found ? { json: { import_id: 'existing-A', status: 'queued' } } : { status: 404, json: { detail: 'not found' } })
    })
    await page.route('**/api/submit-jobs', route => {
      creates++
      return route.fulfill(creates === 1 ? { json: { import_id: 'existing-A', status: 'queued' } } : { status: 409, json: { detail: 'IDEMPOTENCY_CONFLICT' } })
    })
    await openModuleHarness(page)
    const result = await page.evaluate(async () => {
      const jobs = await import('/src/composables/useSubmitJobs.js')
      const first = new FormData(); first.set('raw_text', 'CONTENT_A')
      const changed = new FormData(); changed.set('raw_text', 'CONTENT_B')
      await jobs.submitUploadWithIdempotency(first, { draftId: 'edited-draft' })
      try {
        await jobs.submitUploadWithIdempotency(changed, { draftId: 'edited-draft' })
        return { accepted: true }
      } catch (error) { return { status: error.status, message: error.message } }
    })
    expect(result).toEqual({ status: 409, message: 'IDEMPOTENCY_CONFLICT' })
    expect(creates).toBe(2)
  })
}

test('unchanged draft recovery avoids another upload', async ({ page }) => {
  let creates = 0
  await page.route('**/api/upload-imports/by-key/**', route => route.fulfill(creates
    ? { json: { import_id: 'existing-A', status: 'queued' } }
    : { status: 404, json: { detail: 'not found' } }))
  await page.route('**/api/submit-jobs', route => { creates++; return route.fulfill({ json: { import_id: 'existing-A', status: 'queued' } }) })
  await openModuleHarness(page)
  const result = await page.evaluate(async () => {
    const jobs = await import('/src/composables/useSubmitJobs.js')
    const data = new FormData(); data.set('raw_text', 'CONTENT_A')
    await jobs.submitUploadWithIdempotency(data, { draftId: 'same-draft' })
    return jobs.submitUploadWithIdempotency(data, { draftId: 'same-draft' })
  })
  expect(result.import_id).toBe('existing-A')
  expect(result.created).toBe(false)
  expect(creates).toBe(1)
})

test('an old draft without a fingerprint cannot recover edited content from an existing task', async ({ page }) => {
  await page.route('**/api/upload-imports/by-key/**', route => route.fulfill({
    json: { import_id: 'original-A', status: 'queued' },
  }))
  await page.route('**/api/submit-jobs', route => route.abort('failed'))
  await openModuleHarness(page)
  expect(await page.evaluate(async () => {
    const jobs = await import('/src/composables/useSubmitJobs.js')
    jobs.rememberDraftKey('legacy-draft', 'legacy-key')
    const changed = new FormData(); changed.set('raw_text', 'CONTENT_B')
    try {
      await jobs.submitUploadWithIdempotency(changed, { draftId: 'legacy-draft' })
      return { accepted: true }
    } catch { return { accepted: false } }
  })).toEqual({ accepted: false })
})

test('concurrent different payloads cannot recover another accepted payload after a lost conflict reply', async ({ page }) => {
  const prechecks = []
  let firstPrecheckStarted
  const firstPrecheck = new Promise(resolve => { firstPrecheckStarted = resolve })
  let bothPrechecksStarted
  const bothPrechecks = new Promise(resolve => { bothPrechecksStarted = resolve })
  let firstUploadStarted
  const firstUpload = new Promise(resolve => { firstUploadStarted = resolve })
  let releaseFirstUpload
  const firstUploadGate = new Promise(resolve => { releaseFirstUpload = resolve })
  let lookups = 0
  let creates = 0
  await page.route('**/api/upload-imports/by-key/**', async route => {
    lookups++
    if (lookups <= 2) {
      prechecks.push(route)
      if (prechecks.length === 1) firstPrecheckStarted()
      if (prechecks.length === 2) bothPrechecksStarted()
      return
    }
    await route.fulfill({ json: { import_id: 'accepted-A', status: 'queued' } })
  })
  await page.route('**/api/submit-jobs', async route => {
    creates++
    if (creates === 1) {
      // A has been accepted, but its response has not reached the client yet.
      firstUploadStarted()
      await firstUploadGate
      await route.fulfill({ json: { import_id: 'accepted-A', status: 'queued' } })
    } else {
      // B conflicts with A; the server's conflict reply is lost in transit.
      await route.abort('failed')
    }
  })
  await openModuleHarness(page)
  await page.evaluate(async () => {
    const jobs = await import('/src/composables/useSubmitJobs.js')
    const first = new FormData(); first.set('raw_text', 'CONTENT_A')
    window.concurrentFirst = jobs.submitUploadWithIdempotency(first, { draftId: 'concurrent-draft' })
  })
  await firstPrecheck
  await page.evaluate(async () => {
    const jobs = await import('/src/composables/useSubmitJobs.js')
    const second = new FormData(); second.set('raw_text', 'CONTENT_B')
    window.concurrentSecond = jobs.submitUploadWithIdempotency(second, { draftId: 'concurrent-draft' })
      .then(() => ({ accepted: true }), () => ({ accepted: false }))
  })
  await bothPrechecks
  await prechecks[0].fulfill({ status: 404, json: { detail: 'not found' } })
  await firstUpload
  await prechecks[1].fulfill({ status: 404, json: { detail: 'not found' } })
  const secondResult = await page.evaluate(() => window.concurrentSecond)
  releaseFirstUpload()
  expect(await page.evaluate(() => window.concurrentFirst)).toMatchObject({ import_id: 'accepted-A' })
  expect(secondResult).toEqual({ accepted: false })
  expect(creates).toBe(2)
})
