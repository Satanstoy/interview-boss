import { expect, test } from '@playwright/test'

/**
 * WCAG 4.1.2 — icon-only tooltips must give their trigger an accessible name,
 * including on touch devices where AppTooltip falls back to rendering the bare
 * slot (no hover TooltipContent).
 */

// Mount AppTooltip in the Vite SPA with render functions (avoids runtime
// template compilation), a minimal router for useRoute(), and a
// TooltipProvider (normally provided by App.vue). Asserts the accessible name
// on both the hover and touch fallback branches.
async function mountAppTooltip() {
  const { createApp, h } = await import('/node_modules/.vite/deps/vue.js')
  const { createRouter, createWebHistory } = await import('/node_modules/.vite/deps/vue-router.js')
  const { default: AppTooltip } = await import('/src/components/common/AppTooltip.vue')
  const { TooltipProvider } = await import('/src/components/ui/tooltip')
  const router = createRouter({
    history: createWebHistory(),
    routes: [{ path: '/', component: { render: () => null } }],
  })
  const root = document.createElement('div')
  document.body.appendChild(root)
  const app = createApp({
    render() {
      return h(TooltipProvider, null, () =>
        h(AppTooltip, { text: '删除岗位' }, {
          default: () => h('button', { 'data-testid': 'the-btn' }, '删'),
        }),
      )
    },
  })
  app.use(router)
  await router.isReady()
  app.mount(root)
  await new Promise(resolve => requestAnimationFrame(resolve))
  await new Promise(resolve => setTimeout(resolve, 30))
  const btn = root.querySelector('[data-testid="the-btn"]')
  const srOnly = root.querySelector('.sr-only')
  const r = {
    ariaLabel: btn?.getAttribute('aria-label') || '',
    srOnlyText: srOnly?.textContent?.trim() || '',
    rendered: root.querySelectorAll('button').length > 0,
  }
  app.unmount()
  root.remove()
  return r
}

test('AppTooltip exposes an accessible name on the trigger button (hover devices)', async ({ page }) => {
  await page.goto('/login')
  const result = await page.evaluate(mountAppTooltip)
  expect(result.rendered).toBe(true)
  expect(result.ariaLabel).toBe('删除岗位')
})

test('AppTooltip renders sr-only text for icon-only triggers on touch devices', async ({ page }) => {
  // Force the (hover: hover) and (pointer: fine) media query to report false so
  // supportsHover resolves to the touch fallback branch.
  await page.addInitScript(() => {
    const original = window.matchMedia.bind(window)
    window.matchMedia = (query) => {
      if (String(query).includes('(hover: hover)')) {
        return {
          matches: false,
          media: String(query),
          addEventListener() {},
          removeEventListener() {},
          addListener() {},
          removeListener() {},
          onchange: null,
        }
      }
      return original(query)
    }
  })
  await page.goto('/login')
  const result = await page.evaluate(mountAppTooltip)
  // Accessible name must survive the touch fallback and be reinforced by a
  // sr-only span for assistive technology.
  expect(result.rendered).toBe(true)
  expect(result.ariaLabel).toBe('删除岗位')
  expect(result.srOnlyText).toBe('删除岗位')
})
