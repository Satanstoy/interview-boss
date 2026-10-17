import { chromium } from '/opt/interview-boss/frontend/node_modules/playwright/index.mjs'
import { writeFileSync } from 'node:fs'
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] })
try {
 const page = await browser.newPage()
 page.setDefaultTimeout(15000)
 page.on('pageerror',e=>console.log('PAGE_ERROR',e.message))
 page.on('console',m=>{if(m.type()==='error')console.log('CONSOLE_ERROR',m.text())})
 const requests = []
 let approveBody
 await page.route('**/api/**', async route => {
  const request = route.request()
  const path = new URL(request.url()).pathname
  if (!path.startsWith('/api/')) return route.continue()
  requests.push({path, method:request.method()})
  if (path === '/api/admin/public-contributions/7001/approve') approveBody = request.postDataJSON()
  const data = path === '/api/admin/public-contributions' ? {items:[{
   id:7001, source_type:'interview', status:'pending_review', revision:3,
   summary:{company:'PRIVATE_COMPANY',round:'一面',item_count:5,
    question_previews:[{question:'TCP 三次握手'},{question:'Redis 持久化'},{question:'需要排除的题'}]},
  }],total:1} : {status:'approved',items:[],total:0}
  await route.fulfill({json:data})
 })
 await page.route('**/__spec_review_probe', route => route.fulfill({contentType:'text/html',body:`
  <html><body><div id="app"></div><script type="module">
  import {createApp,ref,onMounted,h} from '/node_modules/.vite/deps/vue.js';
  import Review from '/src/components/business/AdminReview.vue';
  createApp({setup(){const visible=ref(false);onMounted(()=>visible.value=true);return()=>h(Review,{visible:visible.value})}}).mount('#app');
  </script></body></html>`}))
 await page.goto('http://127.0.0.1:18481/__spec_review_probe')
 const approve = page.getByRole('button',{name:'通过',exact:true})
 try { await approve.waitFor({state:'visible'}) } catch(e) {console.log('BODY',await page.locator('body').innerText());console.log('REQUESTS',JSON.stringify(requests));throw e}
 const before = {buttons:await page.getByRole('button').allTextContents(),
  editorCount:await page.locator('input,textarea').count(),
  detailRequests:requests.filter(r=>r.path==='/api/admin/public-contributions/7001').length}
 await approve.click()
 await page.getByText(/暂无待审核贡献/).waitFor({state:'visible'})
 const evidence = {...before, approveBody,apiMock:true,productComponent:'AdminReview.vue'}
 writeFileSync('/opt/interview-boss/.tech-audit/work/2026-10-09/spec-recheck/review-ui-observation.json',JSON.stringify(evidence,null,2)+'\n')
 console.log(JSON.stringify(evidence))
 if (!approveBody?.review_fields) throw new Error('SPEC_GAP: approval has no reviewed projection; UI has no preview/edit/exclude workflow')
} finally { await browser.close() }
