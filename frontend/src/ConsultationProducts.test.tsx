// @vitest-environment jsdom
import React from 'react';
import {act,cleanup,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {ConsultationProducts,consultedProduct,factSections} from './ConsultationProducts';

const products=[
  {id:'ultra',name:'HUAWEI MateBook 14 酷睿 Ultra',cover:'/ultra.png'},
  {id:'harmony',name:'HUAWEI MateBook 14（鸿蒙版）',cover:'/harmony.png'},
  {id:'pro',name:'HUAWEI MateBook Pro',cover:'/pro.png'},
  {id:'pros',name:'HUAWEI MateBook Pro S',cover:'/pros.png'},
];
const message=(content:string)=>({content,role:'customer'});
beforeEach(()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({facts:{body:'## 操作系统\nWindows 11\n## 内存\n16 GB / 32 GB\n*依版本而异。'}})})));
});
afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals();});

it('模糊型号或多产品比较不锁定版本，完整型号及最新产品卡可锁定',()=>{
  expect(consultedProduct(products,[message('这个Mate怎么卖')])).toBeUndefined();
  expect(consultedProduct(products,[message('MateBook 14怎么样')])).toBeUndefined();
  expect(consultedProduct(products,[message('MateBook Pro和MateBook 14（鸿蒙版）比较')])).toBeUndefined();
  expect(consultedProduct(products,[message('MateBook 14 酷睿 Ultra怎么样')])?.id).toBe('ultra');
  expect(consultedProduct(products,[message('MateBook 14（鸿蒙版）')])?.id).toBe('harmony');
  expect(consultedProduct(products,[message('MateBook Pro S怎么样')])?.id).toBe('pros');
  expect(consultedProduct(products,[message('MateBook Pro'),message('我的预算1万')])?.id).toBe('pro');
  expect(consultedProduct(products,[message('MateBook Pro'),{card:{product_id:'harmony'}}])?.id).toBe('harmony');
  expect(consultedProduct(products,[{card:{product_id:'harmony'}},message('换成MateBook Pro S')])?.id).toBe('pros');
  expect(consultedProduct(products,[{card:{product_id:'removed'}}])).toBeUndefined();
});

it('自动轮播可暂停和手动切换，新的明确产品消息停止轮播',async()=>{
  vi.useFakeTimers();
  const view=render(<ConsultationProducts products={products} messages={[]} onAsk={vi.fn()}/>);
  await act(async()=>{});
  expect(screen.getByRole('heading',{name:'MateBook 14 酷睿 Ultra'})).toBeTruthy();
  await act(async()=>{vi.advanceTimersByTime(7000);});
  expect(screen.getByRole('heading',{name:'MateBook 14（鸿蒙版）'})).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'暂停产品轮播'}));
  await act(async()=>{vi.advanceTimersByTime(14000);});
  expect(screen.getByRole('heading',{name:'MateBook 14（鸿蒙版）'})).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'下一款产品'}));
  await act(async()=>{});
  expect(screen.getByRole('heading',{name:'MateBook Pro'})).toBeTruthy();
  view.rerender(<ConsultationProducts products={products} messages={[message('MateBook Pro S')]} onAsk={vi.fn()}/>);
  await act(async()=>{vi.advanceTimersByTime(14000);});
  expect(screen.getByRole('heading',{name:'正在聊的产品'})).toBeTruthy();
  expect(screen.getByRole('heading',{name:'MateBook Pro S'})).toBeTruthy();
  expect(screen.queryByRole('button',{name:'下一款产品'})).toBeNull();
});

it('产品按钮交给输入框处理，缺图时回退，无产品和关闭会话不提供无效操作',async()=>{
  const onAsk=vi.fn();
  const view=render(<ConsultationProducts products={[products[0]]} messages={[]} onAsk={onAsk}/>);
  await act(async()=>{});
  fireEvent.click(screen.getByRole('button',{name:/聊聊这款产品/}));
  expect(onAsk).toHaveBeenCalledWith(products[0].name);
  fireEvent.error(screen.getByRole('img',{name:products[0].name}));
  expect(screen.getByText('产品图片待补充')).toBeTruthy();
  view.rerender(<ConsultationProducts products={[products[0]]} messages={[]} onAsk={onAsk} disabled/>);
  expect((screen.getByRole('button',{name:/聊聊这款产品/}) as HTMLButtonElement).disabled).toBe(true);
  view.rerender(<ConsultationProducts products={[]} messages={[]} onAsk={onAsk}/>);
  expect(screen.getByText('产品资料准备中')).toBeTruthy();
  expect(screen.queryByRole('button',{name:/聊聊这款产品/})).toBeNull();
});

it('规格摘录保留同一段落中的版本限定说明',()=>{
  expect(factSections('## 处理器\nUltra 7\n*仅限 Windows 版本。\n## 来源\nhttps://example.com')[0].body).toContain('*仅限 Windows 版本。');
});
