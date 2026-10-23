// Actual built frontend, isolated replay database, ordinary Chromium (not Codex IAB).
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(path.join(process.env.PLAYWRIGHT_MODULES,'playwright'));
(async()=>{
 const base='http://127.0.0.1:8776',out=process.env.E2E_DATA_DIR;
 const login=JSON.parse(fs.readFileSync(path.join(out,'login.json'),'utf8'));
 const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_EXECUTABLE?{executablePath:process.env.PLAYWRIGHT_EXECUTABLE}:{})});const errors=[];
 try{
  for(const [name,width] of [['desktop',1000],['mobile',390]]){
   const context=await browser.newContext({viewport:{width,height:1000}});
   const response=await context.request.post(base+'/api/auth/login',{data:{username:login.customer,password:login.password},headers:{'X-Store-Request':'1'}});
   assert.equal(response.status(),200);
   const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
   await page.goto(base);await page.locator('.conversation-row').first().click();
   await page.locator('.messages .bubble').nth(3).waitFor();
   const bubbles=page.locator('.messages .bubble');assert.equal(await bubbles.count(),4);
   const historical=bubbles.nth(1),latest=bubbles.nth(3);
   assert.equal(await historical.locator('details').evaluate(e=>e.open),false);
   assert(!/<br>|资料原文|\| ---/.test(await historical.innerText()));
   assert(!/<br>|资料原文|\| ---/.test(await latest.innerText()));
   assert.equal(await latest.locator('details').count(),0);
   await latest.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,name+'-reply.png'),fullPage:true});
   await historical.getByText('查看产品参数',{exact:true}).click();
   assert.equal(await historical.locator('details').evaluate(e=>e.open),true);
   assert((await historical.innerText()).includes('i9-13900H'));
   assert(!/<br>|资料原文|\| ---/.test(await historical.innerText()));
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   await historical.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,name+'-parameters.png'),fullPage:true});
  }
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify({passed:true,views:['desktop','mobile'],errors},null,2));
  console.log('Reply presentation browser verification passed');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
