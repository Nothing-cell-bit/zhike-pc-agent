// @vitest-environment jsdom
import React from 'react';
import {cleanup,fireEvent,render as rtlRender,screen,within,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {DialoguePlan,DialoguePricing} from './DialoguePlan';
import {ConfigProvider} from 'antd';
const render=(node:React.ReactNode)=>rtlRender(<ConfigProvider theme={{token:{motion:false}}}>{node}</ConfigProvider>);
afterEach(cleanup);
it('标准报价已发送后，不因备选优惠或审批价未就绪再次卡住',()=>{
 render(<DialoguePlan state={{goal:'quote',next_owner:'customer',action:{kind:'wait',candidates:[]},quotes:[{level:'L1',state:'ready_for_review',delivery_status:'sent'},{level:'L2',state:'needs_qualification'},{level:'L4',state:'needs_approval'}]}} editable updating={false} onAdopt={vi.fn()}/>);
 expect(screen.getByRole('heading',{name:'等待客户回复'})).toBeTruthy();
 expect(screen.queryByText('等待门店处理')).toBeNull();
});
it('默认只展示一条推荐，更多在居中弹窗展示全部并可采用其他候选',async()=>{
 const adopt=vi.fn();
 const candidates=[0,1,2].map(i=>({id:'c'+i,label:'角度'+i,reply:'候选原文'+i,intro:'候选原文'+i}));
 render(<DialoguePlan state={{action:{id:'a',kind:'inform',candidates},knowledge_retrieval:[{status:'cached',retrieved_at:'2026-10-22T00:06:00Z'}],tasks:[{id:'done',kind:'answer',title:'旧任务',status:'completed'}]}} editable updating={false} onAdopt={adopt}/>);
 expect(screen.getByText('候选原文0')).toBeTruthy();expect(screen.queryByText('候选原文1')).toBeNull();
 expect(screen.queryByText(/ima 缓存|已处理|旧任务/)).toBeNull();
 expect(screen.getAllByRole('button',{name:'采用这条回复'})).toHaveLength(1);
 fireEvent.click(screen.getByRole('button',{name:'更多'}));
 const dialog=await screen.findByRole('dialog',{name:'AI 推荐回复'});
 expect(within(dialog).getAllByRole('button',{name:'采用这条回复'})).toHaveLength(3);
 fireEvent.click(within(dialog).getAllByRole('button',{name:'采用这条回复'})[1]);
 expect(adopt).toHaveBeenCalledExactlyOnceWith('候选原文1','c1');
 await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull());
 expect(screen.getByText('候选原文1')).toBeTruthy();expect(screen.queryByText('候选原文0')).toBeNull();
});
it('只有一条核验通过的推荐时不伪造更多候选',()=>{
 render(<DialoguePlan state={{action:{kind:'inform',candidates:[{id:'one',label:'建议',reply:'唯一有效回复'}]}}} editable updating={false} onAdopt={vi.fn()}/>);
 expect(screen.getByText('唯一有效回复')).toBeTruthy();
 expect(screen.queryByRole('button',{name:'更多'})).toBeNull();
});
it('分析失败显示实际原因，同时保留上次建议',()=>{
 render(<DialoguePlan failed analysisError="接待规划：模型连接中断，自动重试后仍未恢复" state={{action:{kind:'inform',candidates:[{id:'one',label:'原建议',reply:'上次回复'}]}}} editable updating={false} onAdopt={vi.fn()}/>);
 expect(screen.getByText(/接待规划：模型连接中断/)).toBeTruthy();
 expect(screen.getByText('上次回复')).toBeTruthy();
});
it('待门店处理与等待客户回复分开显示，无需重复回复时不显示候选',()=>{
 render(<DialoguePlan state={{goal:'information',next_owner:'staff',response_required:false,waiting_reason:'客户已确认，无需重复回复',action:{kind:'wait',candidates:[]}}} editable updating={false} onAdopt={vi.fn()}/>);
 expect(screen.getByText('等待门店处理')).toBeTruthy();
 expect(screen.getByText('客户已确认，无需重复回复')).toBeTruthy();
 expect(screen.queryByText('等待客户回复')).toBeNull();
});
it('换一组失败时保留候选并在按钮附近显示反馈',()=>{
 const candidates=[0,1,2].map(i=>({id:'c'+i,label:'候选'+i,reply:'原回复'+i}));
 render(<DialoguePlan state={{action:{kind:'inform',candidates}}} editable updating={false} onAdopt={vi.fn()} regenerateError="这次没有生成新的回复，原建议仍可使用。"/>);
 expect(screen.getByText('这次没有生成新的回复，原建议仍可使用。')).toBeTruthy();
 expect(screen.getAllByRole('button',{name:'采用这条回复'})).toHaveLength(1);
});
it('更多候选可独立采用，换一组不触发更新分析',async()=>{
 const adopt=vi.fn(),regenerate=vi.fn(),analyze=vi.fn();
 const candidates=[0,1,2].map(i=>({id:'c'+i,label:'候选'+i,reply:'自然回复'+i,intro:'自然回复'+i}));
 render(<DialoguePlan state={{goal:'information',action:{id:'a',kind:'inform',reply:'内部事实',candidates}}} editable updating={false} onAdopt={adopt} onRegenerate={regenerate} onChanged={analyze}/>);
 expect(screen.queryByText('内部事实')).toBeNull();expect(screen.getAllByRole('button',{name:'采用这条回复'})).toHaveLength(1);
 fireEvent.click(screen.getByRole('button',{name:'更多'}));
 const dialog=await screen.findByRole('dialog',{name:'AI 推荐回复'});
 fireEvent.click(within(dialog).getByRole('button',{name:'换一组回复'}));
 fireEvent.click(within(dialog).getAllByRole('button',{name:'采用这条回复'})[1]);expect(adopt).toHaveBeenCalledWith('自然回复1','c1');expect(regenerate).toHaveBeenCalledOnce();expect(analyze).not.toHaveBeenCalled();
});
it('当前产品主题独立展示，普通问答不带出历史报价',()=>{
 render(<DialoguePlan state={{goal:'information',topic:{subject:'屏幕刷新率'},action:{id:'a',kind:'inform',reply:'资料列出了对应刷新率。',option_ids:[]},selection:{status:'confirmed',option_id:'old'},options:[{id:'old',name:'旧产品',variant:'旧配置'}],quotes:[{option_id:'old',state:'ready_for_review',total_minor:899900}]}} editable onAdopt={vi.fn()} updating={false}/>);
 expect(screen.queryByText('当前咨询 · 屏幕刷新率')).toBeNull();expect(screen.getByText('资料列出了对应刷新率。')).toBeTruthy();expect(screen.queryByText(/旧产品/)).toBeNull();expect(screen.queryByText(/8,999/)).toBeNull();
});
it('区分委托推荐和客户确认，采用只把草稿及动作编号交给输入框',()=>{
 const adopt=vi.fn();render(<DialoguePlan state={{delegation:{quote:'你来选'},selection:{status:'unconfirmed'},action:{id:'a',kind:'recommend',reply:'给您两套真实配置作比较。',option_ids:['v']},options:[{id:'v',name:'电脑甲',variant:'32GB/1TB'}],quotes:[]}} editable onAdopt={adopt} updating={false}/>);
 expect(screen.queryByText('待客户确认')).toBeNull();expect(adopt).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'采用到输入框'}));expect(adopt).toHaveBeenCalledWith('给您两套真实配置作比较。','a');
});
it('缺少有效价格只展示待核价，不把参考快照当成确定金额',()=>{
 render(<DialoguePricing state={{selection:{status:'confirmed'},action:{id:'a',kind:'quote',reply:'价格待核验',option_ids:['v']},options:[{id:'v',name:'电脑甲',variant:'32GB/1TB'}],quotes:[{option_id:'v',state:'needs_price',total_minor:null,reference:{amount_minor:699900}}]}} editable onAdopt={vi.fn()} updating={false}/>);
 expect(screen.getByText('门店价待核验')).toBeTruthy();expect(screen.queryByText('¥6,999')).toBeNull();
});
it('报价说明发送后保留已选配置和核价状态，不再显示旧建议按钮',()=>{
 render(<DialoguePricing state={{goal:'quote',selection:{status:'confirmed',option_id:'v'},action:{kind:'wait',reply:''},options:[{id:'v',name:'电脑甲',variant:'32GB/1TB'}],quotes:[{option_id:'v',state:'needs_configuration',total_minor:null}]}} editable onAdopt={vi.fn()} updating={false}/>);
 expect(screen.getByText(/电脑甲/)).toBeTruthy();expect(screen.getByText('销售组合待核实')).toBeTruthy();expect(screen.queryByRole('button',{name:'采用到输入框'})).toBeNull();
});
it('核价完成后采用可编辑话术，金额由发送时的报价卡提供',()=>{
 const adopt=vi.fn();render(<DialoguePlan state={{goal:'quote',action:{id:'q',kind:'quote',intro:'请查看本次报价。',reply:'请查看本次报价。\n¥8009',option_ids:['v']},options:[{id:'v',name:'电脑甲',variant:'32GB/1TB'}],quotes:[{option_id:'v',state:'ready_for_review',total_minor:800900}]}} editable onAdopt={adopt} updating={false}/>);
 fireEvent.click(screen.getByRole('button',{name:'采用到输入框'}));expect(adopt).toHaveBeenCalledWith('请查看本次报价。','q');
});
