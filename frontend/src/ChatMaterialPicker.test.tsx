// @vitest-environment jsdom
import React from 'react';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ChatMaterialPicker} from './ChatMaterialPicker';
const mocks=vi.hoisted(()=>({api:vi.fn()}));
vi.mock('./api',async original=>({...await original<typeof import('./api')>(),api:mocks.api}));
afterEach(()=>{cleanup();vi.clearAllMocks();});

function responses(){
 mocks.api.mockImplementation(async(path:string)=>path==='/marketing/chat-sources'?
  [{id:'c1',name:'林同学',message_count:2,stage:'了解需求'},{id:'c2',name:'李同学',message_count:1,stage:'比较选型'}]:
  path.includes('c1')?{messages:[{id:'m1',seq:1,role:'customer',content:'需要写代码'},
   {id:'m2',seq:2,role:'staff',content:'先核对软件要求'}],has_more:false}:
  {messages:[{id:'m3',seq:1,role:'customer',content:'图书馆学习'}],has_more:false});
}

it('跨聊天逐条勾选，确认后只返回消息ID，不默认选择其他内容',async()=>{
 responses();const change=vi.fn();render(<ChatMaterialPicker onChange={change}/>);
 expect(mocks.api).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'选择聊天素材'}));
 await screen.findByText('需要写代码');
 fireEvent.click(screen.getByRole('checkbox',{name:'选择消息 m1'}));
 fireEvent.click(screen.getByRole('button',{name:/李同学/}));
 await screen.findByText('图书馆学习');
 fireEvent.click(screen.getByRole('checkbox',{name:'选择消息 m3'}));
 expect(change).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'使用所选素材'}));
 await waitFor(()=>expect(change).toHaveBeenCalledWith(['m1','m3']));
});

it('取消保留原选择，清空可移除之前绑定的素材',async()=>{
 responses();const change=vi.fn();render(<ChatMaterialPicker value={['m1']} onChange={change}/>);
 fireEvent.click(screen.getByRole('button',{name:'选择聊天素材'}));
 await screen.findByText('需要写代码');
 fireEvent.click(screen.getByRole('checkbox',{name:'选择消息 m2'}));
 fireEvent.click(screen.getByRole('button',{name:'取消选择'}));
 expect(change).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'清空聊天素材'}));
 expect(change).toHaveBeenCalledWith([]);
});

it('没有已绑定聊天时给出接待入口说明，不出现默认勾选',async()=>{
 mocks.api.mockResolvedValue([]);render(<ChatMaterialPicker/>);
 fireEvent.click(screen.getByRole('button',{name:'选择聊天素材'}));
 await screen.findByText(/还没有已绑定的聊天/);
 expect(screen.queryByRole('checkbox')).toBeNull();
});
