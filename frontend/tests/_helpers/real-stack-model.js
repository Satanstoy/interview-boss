export async function configureDisposableUserModel(page) {
  const result = await page.evaluate(async () => {
    const refreshed = await fetch('/api/auth/refresh', {
      method: 'POST',
      credentials: 'include',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
    if (!refreshed.ok) return { status: refreshed.status }

    const { token } = await refreshed.json()
    const configured = await fetch('/api/profile/llm', {
      method: 'PUT',
      credentials: 'include',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
      },
      body: JSON.stringify({
        llm_api_key: 'real-stack-e2e-provider-key',
        llm_base_url: 'http://llm-stub:8080/v1',
        llm_model: 'real-stack-stub',
        llm_timeout: '10',
        llm_api_format: 'chat',
      }),
    })
    return { status: configured.status, token }
  })

  if (result.status !== 200) {
    throw new Error(`Could not configure the disposable user model (HTTP ${result.status})`)
  }
  return result.token
}
