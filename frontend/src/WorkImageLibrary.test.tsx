// @vitest-environment jsdom
import React from 'react';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {WorkImageLibrary} from './WorkImageLibrary';
import {workImageUrl} from './workImages';

afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const props={workId:'w1',choices:[],selected:[],disabled:false,onSelect:vi.fn(),onUploaded:vi.fn()};

it('本地上传使用二进制文件，成功后交给编辑器插入，保留错误提示',async()=>{
 const uploaded={id:'upload-abc',name:'upload-abc.png',caption:'学习桌面.png',source_type:'user_upload'};
 const fetch=vi.fn().mockResolvedValueOnce({ok:true,json:async()=>uploaded})
  .mockResolvedValueOnce({ok:false,json:async()=>({detail:'图片无法读取'})});
 vi.stubGlobal('fetch',fetch);const onUploaded=vi.fn();
 render(<WorkImageLibrary {...props} onUploaded={onUploaded}/>);
 const file=new File(['picture'],'学习桌面.png',{type:'image/png'});
 fireEvent.change(screen.getByLabelText('选择本地图片'),{target:{files:[file]}});
 await waitFor(()=>expect(onUploaded).toHaveBeenCalledWith(uploaded));
 expect(fetch).toHaveBeenCalledWith('/api/works/w1/images?filename='+encodeURIComponent(file.name),expect.objectContaining({body:file,method:'POST',headers:{'Content-Type':'image/png','X-Store-Request':'1'}}));
 fireEvent.change(screen.getByLabelText('选择本地图片'),{target:{files:[file]}});
 await screen.findByText(/图片无法读取/);expect(onUploaded).toHaveBeenCalledTimes(1);
});

it('前端拒绝过大或不支持的文件，已满时不再上传',async()=>{
 const fetch=vi.fn();vi.stubGlobal('fetch',fetch);
 const view=render(<WorkImageLibrary {...props}/>);
 fireEvent.change(screen.getByLabelText('选择本地图片'),{target:{files:[new File(['<svg/>'],'a.svg',{type:'image/svg+xml'})]}});
 await screen.findByText(/仅支持/);expect(fetch).not.toHaveBeenCalled();
 const selected=Array.from({length:6},(_,index)=>({id:String(index)}));
 view.rerender(<WorkImageLibrary {...props} selected={selected}/>);
 expect((screen.getByLabelText('选择本地图片') as HTMLInputElement).disabled).toBe(true);
});

it('本地图片预览用私有资产接口，产品图仍使用原图接口',()=>{
 expect(workImageUrl('upload-safe')).toBe('/api/assets/upload-safe');
 expect(workImageUrl('product1')).toBe('/api/knowledge/images/product1');
});
