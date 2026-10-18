// Read-only browser verification of saved real results. No model calls or publication.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(path.join(process.env.PLAYWRIGHT_MODULES,'playwright'));
(async()=>{
 const root=path.resolve(__dirname,'..'),out=path.join(root,'data/acceptance/ima-20261018-v4/browser');fs.mkdirSync(out,{recursive:true});
 const credentials=Object.fromEntries(fs.readFileSync(path.join(root,'data/initial-admin.txt'),'utf8').split(/\r?\n/).filter(x=>x.includes('=')).map(x=>{const i=x.indexOf('=');return [x.slice(0,i),x.slice(i+1)];}));
 const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_EXECUTABLE});
 const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 try{
  const base='http://127.0.0.1:8768';
  const login=await context.request.post(base+'/api/auth/login',{data:credentials,headers:{'X-Store-Request':'1'}});assert.equal(login.status(),200);
  await page.goto(base+'/staff');
  for(const i of [1,3]){
   const saved=JSON.parse(fs.readFileSync(path.join(root,`data/acceptance/ima-20261018-v4/review-${i}-work.json`),'utf8'));
   await page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name:/营销内容/}).click();
   const back=page.getByRole('button',{name:/返回作品库/});if(await back.isVisible())await back.click();
   await page.locator('.work-card').filter({hasText:saved.content.title}).click();
   await page.getByRole('heading',{name:saved.content.title,exact:true}).waitFor();
   const source=i===1?/知识来源：ima/:/知识来源：本地 ZIP.*已回退本地/;
   await page.locator('.content-status').getByText(source).waitFor();
   await page.waitForFunction(()=>Array.from(document.querySelectorAll('.article img')).every(x=>x.complete&&x.naturalWidth>0));
   assert.equal(await page.locator('.article img').count(),i===1?3:1);
   await page.screenshot({path:path.join(out,`case-${i}-preview.png`),animations:'disabled'});
   await page.getByRole('button',{name:'查看创作依据'}).click();
   const dialog=page.getByRole('dialog');await dialog.getByText(source).waitFor();
   await dialog.getByRole('heading',{name:'四、核验结果'}).scrollIntoViewIfNeeded();
   await page.screenshot({path:path.join(out,`case-${i}-verification.png`),animations:'disabled'});
   await dialog.getByRole('button',{name:'Close',exact:true}).click();
   await page.getByRole('button',{name:'编辑内容',exact:true}).click();
   assert((await page.locator('.image-picker button').count())>=saved.content.images.length);
   await page.getByRole('button',{name:'图文预览',exact:true}).click();
   const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:'导出 Markdown',exact:true}).click()]);
   await download.saveAs(path.join(out,`case-${i}-export.md`));
   const text=fs.readFileSync(path.join(out,`case-${i}-export.md`),'utf8');assert(text.includes('一、场景判断')&&text.includes('四、核验结果'));
   assert(text.includes(i===1?'ima共享知识库':'已整体回退本地'));
  }
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({passed:true,model_calls:false,real_saved_cases:[1,3],checks:['source labels','same-model images load','verification details','snapshot image picker','four-part export'],browserErrors:errors},null,2));
  console.log('Real saved ima and local-fallback browser flows passed.');
 }catch(error){await page.screenshot({path:path.join(out,'failure.png'),animations:'disabled'});throw error;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
