// Reception acceptance against a synthetic local database; never the live site.
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const playwright=require(path.join(process.env.PLAYWRIGHT_MODULES,'playwright'));
(async()=>{
 const base='http://127.0.0.1:8775';
 const folder=process.env.E2E_DATA_DIR;
 const login=JSON.parse(fs.readFileSync(path.join(folder,'login.json'),'utf8'));
 const browser=await playwright.chromium.launch({headless:true,...(process.env.PLAYWRIGHT_EXECUTABLE?{executablePath:process.env.PLAYWRIGHT_EXECUTABLE}:{})});
 const staff=await browser.newContext({viewport:{width:1440,height:1000}});
 const admin=await browser.newContext({viewport:{width:1440,height:1000}});
 const page=await staff.newPage();const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const post=async(context,url,body)=>{const r=await context.request.post(base+'/api'+url,{data:body,headers:{'X-Store-Request':'1'}});assert.equal(r.status(),200,await r.text());return r.json();};
 const poll=async(check)=>{for(let n=0;n<80;n++){if(await check())return;await new Promise(r=>setTimeout(r,300));}throw Error('验收条件未满足');};
 try{
  await post(staff,'/auth/login',{username:login.staff,password:login.password});
  await page.goto(base+'/staff');
  await page.getByRole('button',{name:/客户接待/}).first().click();
  await page.getByText('多轮验收夹具',{exact:true}).first().click();
  await page.getByRole('heading',{name:'等待门店处理'}).waitFor();
  await page.getByText('门店核实尚未完成，客户已确认收到，无需重复回复',{exact:true}).waitFor();
  await page.screenshot({path:path.join(folder,'01-waiting-staff.png'),fullPage:true});
  await page.getByRole('button',{name:'开始核实',exact:true}).click();
  await page.getByText('核实处理中',{exact:true}).waitFor();
  await page.getByRole('button',{name:'调整截止时间',exact:true}).click();
  const deadline=new Date(Date.now()+3600000+8*3600000).toISOString().slice(0,16);
  await page.getByLabel('截止时间（北京时间）').fill(deadline);
  await page.getByRole('button',{name:'保存截止时间',exact:true}).click();
  await poll(async()=>{const r=await staff.request.get(base+'/api/notifications');return !(await r.json()).some(x=>x.kind==='verification');});
  await page.getByRole('button',{name:'登记结果',exact:true}).click();
  await page.getByLabel('处理结果').fill('验收夹具：核实记录已确认指定环境。');
  await page.getByRole('button',{name:'保存结果',exact:true}).click();
  await page.getByRole('button',{name:'采用这条回复'}).first().waitFor({timeout:25000});
  assert.equal(await page.getByRole('button',{name:'采用这条回复'}).count(),3);
  let conv=await (await staff.request.get(base+'/api/conversations/'+login.cid)).json();
  assert.equal(conv.messages.length,3); // Result alone never sends a customer message.
  await page.getByRole('button',{name:'采用这条回复'}).first().click();
  await page.locator('.composer-footer').getByRole('button',{name:'发送'}).click();
  await poll(async()=>{conv=await (await staff.request.get(base+'/api/conversations/'+login.cid)).json();return conv.messages.length===4;});
  await post(staff,'/followups/plan',{conversation_id:login.cid,days:[1,3,5]});
  const plans=await (await staff.request.get(base+'/api/followups')).json();
  assert.equal(plans.length,3);assert.deepEqual(plans.map(x=>x.offset_days).sort(),[1,3,5]);
  await page.screenshot({path:path.join(folder,'02-result-sent.png'),fullPage:true});
  await post(admin,'/auth/login',{username:login.admin,password:login.password});
  const management=await admin.newPage();management.on('pageerror',e=>errors.push(e.message));
  await management.goto(base+'/admin');
  await management.getByRole('tab',{name:'报价规则'}).click();
  await management.getByRole('button',{name:'新增规则'}).click();
  await management.getByRole('button',{name:'添加优惠'}).click();
  await management.getByRole('button',{name:'添加商品或服务'}).click();
  await management.getByLabel('商品或服务名称').fill('验收配件');
  await management.screenshot({path:path.join(folder,'03-price-rule-form.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(folder,'acceptance.json'),JSON.stringify({passed:true,checks:['waiting_owner','no_repeated_reply','start_verification','reschedule_deadline','result_auto_analysis','manual_send','135_followups','pricing_form'],errors},null,2));
  console.log('Reception browser acceptance passed');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
