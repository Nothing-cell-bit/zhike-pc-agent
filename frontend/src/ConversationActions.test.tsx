// @vitest-environment jsdom
import React from 'react';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ConversationActions} from './ConversationActions';

afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const conversation={id:'c1',owner_id:'staff-1',status:'active'};
function props(){return {conversation,userId:'staff-1',action:async(fn:()=>Promise<unknown>)=>fn(),confirm:vi.fn(),onChanged:vi.fn(),onAbandoned:vi.fn()};}

it('待接待会话放弃成功后通知父页面，并携带空负责人防止误操作',async()=>{
 const fetcher=vi.fn().mockResolvedValue({ok:true,json:async()=>({ok:true})});vi.stubGlobal('fetch',fetcher);
 const p=props();render(<ConversationActions {...p} conversation={{...conversation,owner_id:null,status:'waiting'}}/>);
 fireEvent.click(screen.getByRole('button',{name:'放弃会话'}));
 await waitFor(()=>expect(p.onAbandoned).toHaveBeenCalledTimes(1));
 expect(fetcher.mock.calls[0][0]).toBe('/api/conversations/c1/abandon');
 expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({expected_owner:null});
});

it.each(['active','closed'])('本人已接待会话（%s）不能放弃',status=>{
 render(<ConversationActions {...props()} conversation={{...conversation,status}}/>);
 expect(screen.queryByRole('button',{name:'放弃会话'})).toBeNull();
 expect(screen.getByRole('button',{name:status==='closed'?'重新打开':'结束接待'})).toBeTruthy();
});

it('其他客服已接待会话不能放弃，仍可接管',()=>{
 render(<ConversationActions {...props()} userId="staff-2"/>);
 expect(screen.queryByRole('button',{name:'放弃会话'})).toBeNull();
 expect(screen.getByRole('button',{name:'接管会话'})).toBeTruthy();
});

it('未认领会话既能认领也能放弃，认领后刷新详情',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({ok:true})}));
 const p=props();render(<ConversationActions {...p} conversation={{...conversation,owner_id:null,status:'waiting'}}/>);
 expect(screen.getByRole('button',{name:'放弃会话'})).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'认领会话'}));
 await waitFor(()=>expect(p.onChanged).toHaveBeenCalled());
 expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/conversations/c1/claim');
});

it('放弃失败时保留当前对话',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,status:409,json:async()=>({detail:'负责人已变化'})}));
 const p=props();const error=vi.fn();p.action=async fn=>{try{return await fn();}catch(e){error(e);}};
 render(<ConversationActions {...p} conversation={{...conversation,owner_id:null,status:'waiting'}}/>);fireEvent.click(screen.getByRole('button',{name:'放弃会话'}));
 await waitFor(()=>expect(error).toHaveBeenCalled());expect(p.onAbandoned).not.toHaveBeenCalled();
});
