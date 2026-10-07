import { chromium } from '/opt/interview-boss/frontend/node_modules/@playwright/test/index.mjs'
import { writeFileSync } from 'node:fs'
const browser = await chromium.launch({headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
const page = await browser.newPage({viewport:{width:1440,height:900}})
const requests=[]; const errors=[]
page.on('pageerror',e=>{errors.push(e.message);console.log('PAGEERROR',e.message)})
page.on('console',m=>{if(m.type()==='error')console.log('CONSOLE',m.text())})
const tasks=Array.from({length:25},(_,i)=>({import_id:`imp-history-${i+1}`,revision:3,status:'completed',target_intent:'private',stage:'answer',position_name:'后端',result:null,allowed_actions:['view_summary'],progress:{total:1,completed:1},counts:{answered:1,failed:0},created_at:'2026-10-07T01:00:00Z'}))
await page.route('**/api/**',async route=>{
 const u=new URL(route.request().url()); if(!u.pathname.startsWith('/api/'))return route.continue(); requests.push({path:u.pathname,search:u.search,method:route.request().method()})
 if(u.pathname==='/api/upload-imports') {const p=Number(u.searchParams.get('page')||1);return route.fulfill({json:{items:tasks.slice((p-1)*20,p*20),total:25,page:p,page_size:20}})}
 if(u.pathname.includes('personal-analysis-queue'))return route.fulfill({json:{items:[],total:0,page:1,page_size:20}})
 return route.fulfill({json:{items:[],total:0}})
})
await page.route('http://127.0.0.1:18441/d15-probe',route=>route.fulfill({contentType:'text/html',body:`<!doctype html><html><head><meta charset="UTF-8"><style>body{font-family:sans-serif}section{border:1px solid #888;width:420px}li{border-bottom:1px solid #ddd;padding:4px}button{margin:3px}</style></head><body><div id="probe"></div><script type="module">
import {createApp} from '/node_modules/.vite/deps/vue.js';
import {createRouter,createMemoryHistory} from '/node_modules/.vite/deps/vue-router.js';
import UploadTaskCenter from '/src/components/business/UploadTaskCenter.vue';
import {currentUser} from '/src/composables/useAuth.js';
currentUser.value={id:101,username:'probe',is_admin:0};
const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{template:'<div/>'}}]});
const app=createApp(UploadTaskCenter);app.use(router);app.mount('#probe');window.probeRouter=router;
</script></body></html>`}))
try {
 await page.goto('http://127.0.0.1:18441/d15-probe')
 await page.getByRole('button',{name:'上传任务中心',exact:true}).click({timeout:30000})
 const center=page.getByRole('region',{name:'上传任务中心'})
 await center.getByText('共 25 条',{exact:true}).waitFor({timeout:15000})
 const before={cards:await center.locator('li').count(),totalText:await center.locator('footer').innerText(),history25Visible:await center.getByText(/imp-history-25/).count(),buttons:await center.locator('button').allTextContents(),requests:requests.filter(r=>r.path==='/api/upload-imports')}
 const apiBefore=requests.length;const textBefore=await center.innerText();const urlBefore=await page.evaluate(()=>window.probeRouter.currentRoute.value.fullPath)
 await center.getByRole('button',{name:'查看摘要',exact:true}).first().click()
 await page.waitForTimeout(500)
 const after={summaryCausedRequests:requests.slice(apiBefore),summaryChangedText:(await center.innerText())!==textBefore,summaryChangedRoute:(await page.evaluate(()=>window.probeRouter.currentRoute.value.fullPath))!==urlBefore}
 await page.screenshot({path:'/tmp/task-center-d15-probe.png',fullPage:true})
 const result={boundary:'current real Vue component; all business API responses mocked; no worker/database/prod validation',before,after,pageErrors:errors};writeFileSync('/tmp/task-center-d15-probe.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2))
 if(before.cards!==20||before.history25Visible!==0||after.summaryChangedText||after.summaryChangedRoute||after.summaryCausedRequests.length)process.exitCode=1
} finally {await browser.close()}
