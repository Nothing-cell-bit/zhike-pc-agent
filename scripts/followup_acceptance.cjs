// Local isolated acceptance; run tests.e2e_server on 8771 first.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(path.join(process.env.PLAYWRIGHT_MODULES,'playwright'));
const base='http://127.0.0.1:8771';
const folder=path.resolve(__dirname,'../tmp/followup-e2e');
const credentials=JSON.parse(fs.readFileSync(path.join(folder,'login.json'),'utf8'));

(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_EXECUTABLE?{executablePath:process.env.PLAYWRIGHT_EXECUTABLE}:{})});
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const customer=await browser.newContext();
 const second=await browser.newContext();
 const page=await context.newPage();const errors=[];
 page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(15000);
 const post=async(ctx,url,body={})=>{
  const response=await ctx.request.post(base+'/api'+url,{data:body,headers:{'X-Store-Request':'1'}});
  assert.equal(response.status(),200,await response.text());return response.json();
 };
 const patch=async(url,body)=>{
  const r=await context.request.patch(base+'/api'+url,{data:body,headers:{'X-Store-Request':'1'}});
  assert.equal(r.status(),200,await r.text());
 };
 try{
  await post(customer,'/auth/guest',{name:'跟进提醒验收客户'});
  const conversation=await post(customer,'/conversations');
  await page.goto(base+'/staff');
  await page.getByRole('button',{name:/登录/}).click();
  await page.getByLabel('用户名',{exact:true}).fill(credentials.username);
  await page.getByLabel('密码',{exact:true}).fill(credentials.password);
  await page.getByRole('dialog').getByRole('button',{name:/登\s*录/}).click();
  await page.getByRole('heading',{name:'工作台'}).waitFor();
  await page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name:/客户接待/}).click();
  await page.getByRole('button',{name:'认领会话',exact:true}).click();
  await page.getByRole('button',{name:'结束接待',exact:true}).waitFor();
  await page.getByRole('button',{name:/安排 1/}).click();
  await page.getByRole('dialog').getByRole('button',{name:'知道了'}).click();
  const followups=await (await context.request.get(base+'/api/followups')).json();
  assert.equal(followups.length,3);
  // Observe a real deadline passing while the page remains open.
  await patch('/followups/'+followups[0].id,{due_at:new Date(Date.now()+5000).toISOString()});
  await page.getByRole('button',{name:'通知与进度，1条到期跟进',exact:true}).waitFor();
  await page.getByText('跟进到期提醒',{exact:true}).waitFor();
  await page.getByRole('button',{name:'通知与进度，1条到期跟进',exact:true}).click();
  const inbox=page.getByRole('region',{name:'到期跟进 · 1'});
  await inbox.getByText('跟进提醒验收客户',{exact:true}).waitFor();
  await page.screenshot({path:path.join(folder,'due-reminder.png'),fullPage:true});
  await inbox.getByRole('button',{name:'去处理'}).click();
  await page.getByRole('dialog',{name:'跟进事项'}).waitFor();
  await page.getByRole('dialog',{name:'跟进事项'}).getByTitle('待处理',{exact:true}).click();
  await page.getByTitle('已完成',{exact:true}).click();
  await page.getByLabel('本次反馈与结果').fill('已联系客户，确认到店时间');
  await page.getByRole('button',{name:'保存记录'}).click();
  await page.getByRole('dialog',{name:'跟进事项'}).waitFor({state:'hidden'});
  await page.getByRole('button',{name:'通知与进度',exact:true}).waitFor();
  assert.deepEqual(await (await context.request.get(base+'/api/notifications')).json(),[]);
  await patch('/followups/'+followups[1].id,{due_at:new Date(Date.now()-1000).toISOString()});
  await page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name:/客户接待/}).click();
  await page.getByRole('button',{name:'接待会话',exact:true}).click();
  await page.getByRole('button',{name:'放弃会话'}).click();
  await page.locator('.conversation-item').waitFor({state:'hidden'});
  await page.reload();
  await page.getByRole('navigation',{name:'主导航'}).getByRole('button',{name:/客户接待/}).click();
  await page.getByText('等待客户开始咨询',{exact:true}).waitFor();
  assert.deepEqual(await (await context.request.get(base+'/api/notifications')).json(),[]);
  await post(context,'/admin/users',{username:'followup_second',password:'LocalFollowupTest123!',display_name:'接手顾问',role:'staff'});
  await post(second,'/auth/login',{username:'followup_second',password:'LocalFollowupTest123!'});
  assert((await (await second.request.get(base+'/api/conversations')).json()).some(c=>c.id===conversation.id));
  await post(second,'/conversations/'+conversation.id+'/claim');
  assert.equal((await (await second.request.get(base+'/api/notifications')).json()).length,1);
  assert.equal((await (await customer.request.get(base+'/api/conversations/'+conversation.id)).json()).messages.length,0);
  await page.screenshot({path:path.join(folder,'abandoned-hidden.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(folder,'result.json'),JSON.stringify({passed:true,checks:['deadline badge and prompt','message list and direct handling','completion clears reminder','abandon persists after reload','new owner receives pending reminder','no automated customer messages'],browserErrors:errors},null,2));
  console.log('PASS: deadline reminder, message handling, durable abandon, reassignment, no customer auto-send');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
