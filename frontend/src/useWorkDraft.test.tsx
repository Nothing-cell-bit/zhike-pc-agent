// @vitest-environment jsdom
import {act,cleanup,renderHook} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ApiError} from './api';
import {useWorkDraft} from './useWorkDraft';
const mock=vi.hoisted(()=>({api:vi.fn()}));
vi.mock('./api',async original=>({...await original<typeof import('./api')>(),api:mock.api}));
const initial={id:'work1',version:1,brief:{platform:'公众号'},content:{title:'原始标题',intro:'导语',body:'## 第一节\n\n正文',cta:'到店体验',tags:[],pending:[],images:[]},report:{status:'passed'}};
afterEach(()=>{cleanup();vi.useRealTimers();vi.clearAllMocks();});
it('停止输入后自动保存，带版本号并保持文档结构',async()=>{
 vi.useFakeTimers();mock.api.mockImplementation(async(path:string,method:string)=>method==='PATCH'?{ok:true}:{...initial,version:2,content:{...initial.content,title:'新标题'},report:{status:'unchecked'}});
 const {result}=renderHook(()=>useWorkDraft(initial));
 act(()=>result.current.change({title:'新标题'}));expect(result.current.dirty).toBe(true);
 await act(async()=>{await vi.advanceTimersByTimeAsync(2200);});
 expect(mock.api).toHaveBeenCalledWith('/works/work1','PATCH',expect.objectContaining({title:'新标题',expected_version:1}));
 expect(result.current.dirty).toBe(false);expect(result.current.work.version).toBe(2);
});
it('保存进行中继续输入，不会被返回的旧快照覆盖',async()=>{
 let resolve!:()=>void;const pending=new Promise<void>(r=>resolve=r);
 mock.api.mockImplementation(async(path:string,method:string)=>{if(method==='PATCH'){await pending;return {ok:true};}return {...initial,version:2,content:{...initial.content,title:'第一次修改'}};});
 const {result}=renderHook(()=>useWorkDraft(initial));act(()=>result.current.change({title:'第一次修改'}));
 let saving!:Promise<unknown>;act(()=>{saving=result.current.save();});act(()=>result.current.change({title:'继续输入的修改'}));
 await act(async()=>{resolve();await saving;});
 expect(result.current.draft.title).toBe('继续输入的修改');expect(result.current.dirty).toBe(true);expect(result.current.work.version).toBe(2);
});
it('版本冲突保留本地内容并停止自动重试',async()=>{
 vi.useFakeTimers();mock.api.mockRejectedValue(new ApiError('作品已更新，请刷新后再保存',409));
 const {result}=renderHook(()=>useWorkDraft(initial));act(()=>result.current.change({title:'本地草稿'}));
 await act(async()=>{await vi.advanceTimersByTimeAsync(2200);});
 expect(result.current.error).toContain('作品已更新');expect(result.current.draft.title).toBe('本地草稿');
 await act(async()=>{await vi.advanceTimersByTimeAsync(10000);});expect(mock.api).toHaveBeenCalledTimes(1);
});
