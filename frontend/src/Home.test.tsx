// @vitest-environment jsdom
import React from 'react';
import {cleanup,fireEvent,render,screen,within} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {Home,followupTime,pendingFollowups} from './Home';

afterEach(cleanup);
const followups=[{id:'later',status:'pending',due_at:'2026-10-19T02:00:00Z',customer_name:'王女士',purpose:'补充需求'},{id:'done',status:'completed',due_at:'2026-10-17T00:00:00Z'},{id:'first',status:'pending',due_at:'2026-10-18T07:00:00Z',customer_name:'林同学',purpose:'确认专业软件'}];
const works=[{id:'work-one',updated_at:'2026-10-18T06:00:00Z',content:{title:'开学选购清单',images:[]},brief:{platform:'小红书'}}];

it('三个业务入口和新建内容均导航到实际功能',()=>{
 const navigate=vi.fn();render(<Home summary={{waiting:3,works:12}} productsCount={10} followups={followups} works={works} navigate={navigate}/>);
 for(const [name,target] of [['客户接待','chat'],['营销内容','works'],['产品资料','products']]){
  fireEvent.click(screen.getByRole('button',{name:new RegExp(name)}));expect(navigate).toHaveBeenLastCalledWith(target);
 }
 fireEvent.click(screen.getByRole('button',{name:/新建内容/}));expect(navigate).toHaveBeenLastCalledWith('create');
});

it('按时间显示未完成跟进，打开具体跟进和作品',()=>{
 const navigate=vi.fn();render(<Home summary={{waiting:0,works:1}} productsCount={10} followups={followups} works={works} navigate={navigate}/>);
 const section=screen.getByRole('region',{name:'待办跟进'});
 expect(within(section).getAllByRole('button',{name:'跟进'})[0].closest('li')?.textContent).toContain('林同学');
 fireEvent.click(within(section).getAllByRole('button',{name:'跟进'})[0]);expect(navigate).toHaveBeenLastCalledWith('followups','first');
 fireEvent.click(screen.getByRole('button',{name:'打开'}));expect(navigate).toHaveBeenLastCalledWith('works','work-one');
 expect(pendingFollowups(followups).map(x=>x.id)).toEqual(['first','later']);
 expect(followups[0].id).toBe('later');
});

it('无数据时显示真实空状态，不填充示例客户和作品',()=>{
 render(<Home summary={{waiting:0,works:0}} productsCount={0} followups={[]} works={[]} navigate={vi.fn()}/>);
 expect(screen.getByText('暂无待办跟进')).toBeTruthy();expect(screen.getByText('暂无作品')).toBeTruthy();expect(screen.queryByText(/林同学/)).toBeNull();
});

it('相对日期使用北京时间，包括跨UTC日期的今天和明天',()=>{
 const now=new Date('2026-10-18T17:00:00Z');
 expect(followupTime('2026-10-18T18:00:00Z',now)).toBe('今天 02:00');
 expect(followupTime('2026-10-19T18:00:00Z',now)).toBe('明天 02:00');
});
