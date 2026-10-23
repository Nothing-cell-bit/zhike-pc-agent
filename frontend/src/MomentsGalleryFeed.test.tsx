// @vitest-environment jsdom
import React from 'react';
import {cleanup,render,screen} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {PlatformArticlePreview} from './PlatformArticlePreview';
const mocks=vi.hoisted(()=>({api:vi.fn(),previous:null as any}));
vi.mock('./api',async original=>({...await original<typeof import('./api')>(),api:mocks.api}));
vi.mock('./lifecycle',()=>({useData:()=>({data:{gallery:null,previous_gallery:mocks.previous},error:'',refresh:vi.fn()})}));
afterEach(()=>{cleanup();vi.clearAllMocks();mocks.previous=null;});
it('朋友圈预览在文案保存或确认升级版本后仍显示已有三图，使用当前正文',()=>{
 mocks.previous={id:'g1',work_id:'w1',work_version:2,product_id:'p1',items:Array.from({length:3},(_,index)=>({image_id:'p'+index,url:'/api/knowledge/images/p'+index,title:'保留配图'+index}))};
 const work={id:'w1',version:3,brief:{platform:'朋友圈',product_id:'p1'}};
 render(<PlatformArticlePreview work={work} content={{body:'修改后的朋友圈正文',images:[]}}/>);
 expect(screen.getByText('修改后的朋友圈正文')).toBeTruthy();
 expect(screen.getAllByAltText(/保留配图/)).toHaveLength(3);
 expect(mocks.api).not.toHaveBeenCalled();
});
it('预览不沿用其他作品、其他产品或未来版本的相册',()=>{
 const work={id:'w1',version:3,brief:{platform:'朋友圈',product_id:'p1'}};
 for(const metadata of [{work_id:'another',product_id:'p1',work_version:2},{work_id:'w1',product_id:'another',work_version:2},{work_id:'w1',product_id:'p1',work_version:4}]){
  mocks.previous={...metadata,id:'g1',items:[{url:'/api/assets/unrelated',title:'错误配图'}]};
  const view=render(<PlatformArticlePreview work={work} content={{body:'当前正文',images:[]}}/>);
  expect(screen.queryByAltText('错误配图')).toBeNull();view.unmount();
 }
});
