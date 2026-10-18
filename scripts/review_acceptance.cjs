// Run only with tests.review_e2e_server and an isolated E2E_DATA_DIR.
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require(path.join(process.env.PLAYWRIGHT_MODULES,'playwright'));

(async()=>{
 const base='http://127.0.0.1:8779';
 for(let attempt=0;attempt<40;attempt++){
  try{if((await fetch(base+'/api/store')).ok)break;}catch{}
  if(attempt===39)throw new Error('Test server did not become ready');
  await new Promise(resolve=>setTimeout(resolve,250));
 }
 const credentials=JSON.parse(fs.readFileSync(path.join(process.env.E2E_DATA_DIR,'login.json'),'utf8'));
 const out=path.join(__dirname,'../tmp/review-acceptance');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  const login=await context.request.post(base+'/api/auth/login',{data:credentials,headers:{'X-Store-Request':'1'}});
  assert.equal(login.status(),200);
  await page.goto(base+'/staff');
  const library=async()=>{await page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name:'营销内容'}).click();};
  await library();
  await page.locator('.work-card').filter({hasText:'测试：自动调整'}).filter({hasNotText:'失败'}).click();
  await page.getByText('请删除全网最低的表述',{exact:false}).waitFor();
  await page.locator('.content-status').screenshot({path:path.join(out,'review-actions.png')});
  await page.getByRole('button',{name:'自动调整并检查'}).click();
  await page.getByText('正在处理当前版本，请稍候。').waitFor();
  assert(await page.getByRole('button',{name:'人工确认通过'}).isDisabled());
  await page.locator('.content-status .ant-tag').filter({hasText:'可使用'}).waitFor({timeout:20000});
  assert.equal(await page.locator('article h1').innerText(),'测试夹具：学习电脑选购清单');
  await page.getByRole('button',{name:'← 返回作品库'}).click();
  await page.locator('.work-card').filter({hasText:'测试：人工确认'}).click();
  await page.locator('.content-status').getByText('门店活动需要确认',{exact:false}).waitFor();
  assert.equal(await page.locator('.content-status').getByText('门店活动需要确认',{exact:false}).count(),1);
  await page.getByRole('button',{name:'人工确认通过'}).click();
  assert(await page.getByRole('button',{name:'确认通过当前版本'}).isDisabled());
  await page.getByLabel('确认说明').fill('已核实活动和产品描述，确认当前版本可用');
  await page.getByRole('button',{name:'确认通过当前版本'}).click();
  await page.getByRole('dialog').waitFor({state:'hidden'});
  await page.locator('.content-status .ant-tag').filter({hasText:'人工已通过'}).waitFor();
  await page.locator('.content-status').screenshot({path:path.join(out,'manual-approved.png')});
  const downloadEvent=page.waitForEvent('download');
  await page.getByRole('button',{name:'导出 Markdown'}).click();
  const download=await downloadEvent;const exported=path.join(out,'approved.md');await download.saveAs(exported);
  assert(fs.readFileSync(exported,'utf8').includes('已核实活动和产品描述'));
  await page.getByRole('button',{name:'编辑内容',exact:true}).click();
  await page.getByLabel('标题',{exact:true}).fill('人工通过后再次修改');
  assert(await page.getByRole('button',{name:'人工确认通过'}).isDisabled());
  await page.getByRole('button',{name:'保存修改'}).click();
  await page.locator('.content-status .ant-tag').filter({hasText:'待检查'}).waitFor();
  await page.getByRole('button',{name:'导出草稿 Markdown'}).waitFor();
  await page.getByRole('button',{name:'← 返回作品库'}).click();
  await page.locator('.work-card').filter({hasText:'测试：自动调整失败'}).click();
  await page.getByRole('button',{name:'自动调整并检查'}).click();
  await page.locator('.content-status').getByText('测试连接失败，原稿已保留').waitFor({timeout:20000});
  assert(await page.getByRole('button',{name:'人工确认通过'}).isEnabled());
  assert.equal(await page.locator('article h1').innerText(),'测试：自动调整失败');
  await page.setViewportSize({width:390,height:844});
  await page.locator('.content-status').scrollIntoViewIfNeeded();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.locator('.content-status').screenshot({path:path.join(out,'review-mobile.png')});
  assert.deepEqual(errors,[]);
  console.log('PASS: automatic repair, pending-only review, manual approval, formal export, edit invalidation, failure recovery, mobile layout');
 }catch(error){await page.screenshot({path:path.join(out,'failure.png'),fullPage:true});throw error;}
 finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
