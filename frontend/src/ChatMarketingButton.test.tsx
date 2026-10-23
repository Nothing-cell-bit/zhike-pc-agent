// @vitest-environment jsdom
import React from 'react';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ChatMarketingButton} from './ChatMarketingButton';
const mocks=vi.hoisted(()=>({api:vi.fn()}));
vi.mock('./api',()=>({api:mocks.api}));
afterEach(()=>{cleanup();vi.clearAllMocks();});

it('读取当前聊天预填数据后才跳转，保留产品、场景、预算和消息ID',async()=>{
 const brief={product_id:'p1',audience:'大学新生',scene:'学习写代码；必用软件：Codex',emphasis:'预算：6000元以内',chat_message_ids:['m1','m2'],import_context:{message_count:2}};
 mocks.api.mockResolvedValue(brief);const imported=vi.fn();
 render(<ChatMarketingButton conversationId="chat-1" productId="p1" disabled={false} onImport={imported}/>);
 fireEvent.click(screen.getByRole('button',{name:/转为营销创作任务/}));
 await waitFor(()=>expect(imported).toHaveBeenCalledWith(brief));
 expect(mocks.api).toHaveBeenCalledWith('/conversations/chat-1/marketing-brief?product_id=p1');
});

it('失败时留在聊天，未绑定时不允许导入',async()=>{
 const imported=vi.fn();mocks.api.mockRejectedValue(new Error('聊天已经解除绑定'));
 const view=render(<ChatMarketingButton conversationId="chat-1" productId="" disabled={false} onImport={imported}/>);
 fireEvent.click(screen.getByRole('button',{name:/转为营销创作任务/}));await screen.findByText('聊天已经解除绑定');
 expect(imported).not.toHaveBeenCalled();
 view.rerender(<ChatMarketingButton conversationId="chat-1" productId="" disabled onImport={imported}/>);
 expect((screen.getByRole('button',{name:/转为营销创作任务/}) as HTMLButtonElement).disabled).toBe(true);
});

it('离开当前聊天后不让迟到的请求把用户跳回创作页',async()=>{
 let resolve!:(value:any)=>void;mocks.api.mockReturnValue(new Promise(done=>{resolve=done;}));const imported=vi.fn();
 const view=render(<ChatMarketingButton conversationId="chat-1" productId="" disabled={false} onImport={imported}/>);
 fireEvent.click(screen.getByRole('button',{name:/转为营销创作任务/}));view.unmount();
 resolve({scene:'旧聊天素材'});await Promise.resolve();expect(imported).not.toHaveBeenCalled();
});
