// @vitest-environment jsdom
import {act, renderHook, waitFor, cleanup} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import {useData, watchJob} from './lifecycle';

afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.useRealTimers();});

describe('页面切换与断线恢复',()=>{
 it('旧会话迟到的响应不能覆盖新会话',async()=>{
  let finishOld:(value:unknown)=>void=()=>{};
  vi.stubGlobal('fetch',vi.fn((url:string)=>url.endsWith('/old')?new Promise(resolve=>{finishOld=resolve;}):Promise.resolve({ok:true,json:async()=>({id:'new'})})));
  const hook=renderHook(({path})=>useData(path),{initialProps:{path:'/old'}});
  hook.rerender({path:'/new'});
  await waitFor(()=>expect(hook.result.current.data?.id).toBe('new'));
  await act(async()=>{finishOld({ok:true,json:async()=>({id:'old'})});});
  expect(hook.result.current.data.id).toBe('new');
 });
 it('切换资源时立即隐藏旧详情',async()=>{
  vi.stubGlobal('fetch',vi.fn((url:string)=>url.endsWith('/old')?Promise.resolve({ok:true,json:async()=>({id:'old'})}):new Promise(()=>{})));
  const hook=renderHook(({path})=>useData(path),{initialProps:{path:'/old'}});
  await waitFor(()=>expect(hook.result.current.data?.id).toBe('old'));
  hook.rerender({path:'/new'});
  expect(hook.result.current.data).toBeNull();
 });
 it('SSE断线后轮询直到完成且只回调一次',async()=>{
  vi.useFakeTimers();
  let stream:any;
  vi.stubGlobal('EventSource',class{onmessage:any;onerror:any;close=vi.fn();constructor(){stream=this;}});
  const fetcher=vi.fn().mockResolvedValueOnce({ok:true,json:async()=>({status:'running'})}).mockResolvedValue({ok:true,json:async()=>({status:'completed',result:{work_id:'saved'}})});
  vi.stubGlobal('fetch',fetcher);
  const received=vi.fn(),done=vi.fn();
  const stop=watchJob('task',received,done);
  stream.onerror();
  await vi.advanceTimersByTimeAsync(5000);
  expect(done).toHaveBeenCalledTimes(1);
  expect(done.mock.calls[0][0].result.work_id).toBe('saved');
  stop();
 });
});
