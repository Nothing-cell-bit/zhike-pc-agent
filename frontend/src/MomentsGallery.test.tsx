// @vitest-environment jsdom
import React from 'react';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {MomentsGalleryGrid,MomentsGalleryStudio} from './MomentsGallery';
const mocks=vi.hoisted(()=>({api:vi.fn(),refresh:vi.fn(),jobs:[] as any[],album:null as any,previous:null as any}));
vi.mock('./api',async original=>({...await original<typeof import('./api')>(),api:mocks.api,requestId:()=> 'gallery-ui-request-001'}));
vi.mock('./lifecycle',()=>({useData:(path:string)=>({data:path==='/jobs'?mocks.jobs:{gallery:mocks.album,previous_gallery:mocks.previous},error:'',refresh:mocks.refresh})}));
afterEach(()=>{cleanup();vi.clearAllMocks();mocks.jobs=[];mocks.album=null;mocks.previous=null;});
it('九宫格是九张独立图片，保持顺序并支持单图预览',()=>{
 const items=Array.from({length:9},(_,index)=>({kind:index%3?'ai':'original',url:'/api/assets/picture-'+index,title:'学习配图'+(index+1)}));
 const move=vi.fn();const {container}=render(<MomentsGalleryGrid items={items} onMove={move}/>);
 expect(container.querySelector('[data-count="9"]')).toBeTruthy();
 const pictures=screen.getAllByAltText(/学习配图/);expect(pictures.length).toBe(9);
 expect(pictures.map(image=>image.getAttribute('src'))).toEqual(items.map(item=>item.url));
 fireEvent.click(screen.getByRole('button',{name:'第2张向前移动'}));expect(move).toHaveBeenCalledWith(1,0);
});
it('九宫格提交前明确显示3原图加6AI，并提交绑定文案版本的同一次请求',async()=>{
 mocks.api.mockResolvedValue({job_id:'gallery-job'});
 const work={id:'w1',version:2,brief:{platform:'朋友圈',scene:'学习和写代码'},report:{status:'passed'},available_images:[{id:'a'},{id:'b'},{id:'c'}]};
 render(<MomentsGalleryStudio work={work} dirty={false}/>);
 expect(screen.getByText(/3张产品原图 ＋ 6张AI场景图/)).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'生成九宫格配图'}));
 await waitFor(()=>expect(mocks.api).toHaveBeenCalledWith('/works/w1/moments-gallery-tasks','POST',{expected_version:2,count:9,mode:'mixed',scene:'学习和写代码',request_id:'gallery-ui-request-001'}));
});
it('原图不足时不允许重复凑九张，文案未保存时也不提交生图',()=>{
 const work={id:'w1',version:1,brief:{platform:'朋友圈',scene:'学习',moments_image_count:9,moments_image_mode:'original'},report:{status:'passed'},available_images:[{id:'a'}]};
 render(<MomentsGalleryStudio work={work} dirty/>);
 expect(screen.getByText(/当前只有1张同型号原图/)).toBeTruthy();
 expect((screen.getByRole('button',{name:'准备产品配图'}) as HTMLButtonElement).disabled).toBe(true);
 expect(mocks.api).not.toHaveBeenCalled();
});
