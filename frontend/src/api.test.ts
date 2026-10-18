import {describe,it,expect,vi,afterEach} from 'vitest';
import {api,requestId,time} from './api';

afterEach(()=>vi.unstubAllGlobals());
describe('请求边界',()=>{
 it('携带同源会话和防跨站请求头',async()=>{
  const fetcher=vi.fn().mockResolvedValue({ok:true,json:async()=>({ok:true})});vi.stubGlobal('fetch',fetcher);
  await api('/conversations','POST',{name:'test'});
  const [url,opts]=fetcher.mock.calls[0];expect(url).toBe('/api/conversations');expect(opts.credentials).toBe('same-origin');expect(opts.headers['X-Store-Request']).toBe('1');
 });
 it('显示服务端中文失败原因',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,json:async()=>({detail:'请先认领会话'})}));
  await expect(api('/test')).rejects.toThrow('请先认领会话');
 });
 it('局域网HTTP无randomUUID时仍能生成去重编号',()=>{
  vi.stubGlobal('crypto',{getRandomValues:(a:Uint8Array)=>{a.fill(7);return a;}});
  expect(requestId()).toHaveLength(40);
 });
 it('日期按北京时间显示',()=>{expect(time('2026-10-18T00:00:00Z')).toContain('08:00');});
});
