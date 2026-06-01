import { test as setup, expect } from '@playwright/test'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const authFile = path.join(__dirname, '.auth/user.json')

setup('authenticate', async ({ request }) => {
  const response = await request.post('http://localhost:8000/api/auth/login', {
    data: {
      username: 'sj',
      password: 'qnmlgb233..',
      remember_me: true,
    },
  })
  expect(response.ok()).toBeTruthy()

  // Extract set-cookie headers
  const setCookie = response.headersArray().filter(h => h.name.toLowerCase() === 'set-cookie')

  const cookies = []
  for (const h of setCookie) {
    const parts = h.value.split(';').map(s => s.trim())
    const [nameValue, ...attrs] = parts
    const [name, value] = nameValue.split('=')
    const cookie = {
      name: name.trim(),
      value: value || '',
      domain: 'localhost',
      path: '/',
    }
    for (const attr of attrs) {
      const [k, v] = attr.split('=')
      const key = k.trim().toLowerCase()
      if (key === 'httponly') cookie.httpOnly = true
      if (key === 'secure') cookie.secure = false  // localhost is HTTP
      if (key === 'samesite') {
        const sv = v.trim().toLowerCase()
        cookie.sameSite = sv === 'strict' ? 'Strict' : sv === 'lax' ? 'Lax' : sv === 'none' ? 'None' : 'Strict'
      }
      if (key === 'path') cookie.path = v.trim()
      if (key === 'max-age') cookie.expires = Math.floor(Date.now() / 1000) + parseInt(v)
    }
    cookies.push(cookie)
  }

  const state = { cookies, origins: [] }
  const fs = await import('fs')
  fs.mkdirSync(path.join(__dirname, '.auth'), { recursive: true })
  fs.writeFileSync(authFile, JSON.stringify(state, null, 2))
})
