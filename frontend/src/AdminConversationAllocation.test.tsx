// @vitest-environment jsdom
import React from 'react';
import {App} from 'antd';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {AdminConversationAllocation} from './AdminConversationAllocation';
const mocks=vi.hoisted(()=>({api:vi.fn(),refresh:vi.fn(),data:null as any}));
vi.mock('./api',async original=>({...await original<typeof import('./api')>(),api:mocks.api}));
vi.mock('./lifecycle',()=>({useData:()=>({data:mocks.data,error:'',refresh:mocks.refresh})}));
beforeEach(()=>{
 vi.stubGlobal('matchMedia',()=>({matches:false,addListener:vi.fn(),removeListener:vi.fn(),addEventListener:vi.fn(),removeEventListener:vi.fn()}));
 mocks.data={summary:{total:3,active:1,unassigned:1,closed:1},staff:[{id:'s1',display_name:'客服甲',active:true,active_count:1,pending_followups:2}],conversations:[
  {id:'c1',customer_name:'客户甲',owner_id:null,owner_name:'未分配',status:'waiting',stage:'新咨询',message_count:2},
  {id:'c2',customer_name:'客户乙',owner_id:'old-owner',owner_name:'旧客服',owner_active:true,status:'active',stage:'需求确认',message_count:3},
  {id:'c3',customer_name:'客户丙',owner_id:'old-owner',owner_name:'旧客服',owner_active:true,status:'closed',stage:'已成交',message_count:5}]};
});
afterEach(()=>{cleanup();vi.clearAllMocks();vi.unstubAllGlobals();});
const element=()=> <App><AdminConversationAllocation onAccounts={vi.fn()}/></App>;
async function choose(label:string){fireEvent.mouseDown(screen.getByRole('combobox',{name:'分配给客服'}));fireEvent.click(await screen.findByText(label));}

it('单条分配提交原负责人快照，不会先行改动聊天内容',async()=>{
 mocks.api.mockResolvedValue({count:1});render(element());
 expect((screen.getByRole('checkbox',{name:'选择对话 客户丙'}) as HTMLInputElement).disabled).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'分配 客户甲'}));
 await choose('客服甲 · 接待中 1');fireEvent.click(screen.getByRole('button',{name:'确认分配'}));
 await waitFor(()=>expect(mocks.api).toHaveBeenCalledWith('/admin/conversations/assign','POST',{owner_id:'s1',conversations:[{id:'c1',expected_owner:null}]}));
});

it('批量退回保留选择时的负责人，刷新数据不会悄悄覆盖别人新的分配',async()=>{
 mocks.api.mockRejectedValue(new Error('有对话的负责人已变化，请刷新后重新选择'));
 const view=render(element());
 fireEvent.click(screen.getByRole('checkbox',{name:'选择对话 客户甲'}));fireEvent.click(screen.getByRole('checkbox',{name:'选择对话 客户乙'}));
 fireEvent.click(screen.getByRole('button',{name:'批量分配'}));
 mocks.data={...mocks.data,conversations:mocks.data.conversations.map((row:any)=>row.id==='c2'?{...row,owner_id:'new-owner',owner_name:'新客服'}:row)};
 view.rerender(element());await choose('退回待分配');fireEvent.click(screen.getByRole('button',{name:'确认分配'}));
 await waitFor(()=>expect(mocks.api).toHaveBeenCalledWith('/admin/conversations/assign','POST',{owner_id:null,conversations:[{id:'c1',expected_owner:null},{id:'c2',expected_owner:'old-owner'}]}));
 await screen.findByText('有对话的负责人已变化，请刷新后重新选择');
 fireEvent.click(screen.getByRole('button',{name:'重新选择'}));
 expect((screen.getByRole('button',{name:'批量分配'}) as HTMLButtonElement).disabled).toBe(true);
});
