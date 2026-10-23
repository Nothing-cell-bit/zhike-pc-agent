// @vitest-environment jsdom
import React from 'react';
import {Editor} from '@tiptap/core';
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import WorkEditor from './WorkEditor';
const mocks=vi.hoisted(()=>({api:vi.fn()}));
vi.mock('./api',async original=>({...await original<typeof import('./api')>(),api:mocks.api}));
vi.mock('./AiPosterStudio',()=>({AiPosterStudio:()=>null}));
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.clearAllMocks();});

it('真实富文本上传后立即插入，并保留尚未保存的标题及图片位置',async()=>{
 const image={id:'upload-test',name:'upload-test.png',caption:'本地学习桌面.png',source_type:'user_upload'};
 const work={id:'w1',version:1,brief:{platform:'公众号',product_id:'p1'},content:{title:'原始标题',intro:'导语',body:'原始正文',cta:'咨询',images:[],tags:[],pending:[]},available_images:[],versions:[],report:{status:'unchecked',issues:[],pending:[]}};
 mocks.api.mockImplementation(async(_path:string,method:string)=>method==='PATCH'?{ok:true}:work);
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>image}));
 const ctx={id:'w1',onBack:vi.fn(),products:[],navigate:vi.fn(),modal:{confirm:vi.fn(),info:vi.fn()} as any,action:async(fn:any)=>fn(),watch:vi.fn()};
 render(<WorkEditor {...ctx}/>);
 const title=await screen.findByRole('textbox',{name:'作品标题'});
 await waitFor(()=>expect(title.textContent).toBe('原始标题'));
 act(()=>{(title as HTMLElement&{editor:Editor}).editor.commands.setContent('<p>尚未保存的新标题</p>');});
 fireEvent.click(screen.getByRole('button',{name:'插入配图'}));
 const input=await screen.findByLabelText('选择本地图片');
 fireEvent.change(input,{target:{files:[new File(['photo'],'本地学习桌面.png',{type:'image/png'})]}});
 const body=screen.getByRole('textbox',{name:'正文',hidden:true});
 await waitFor(()=>expect(body.querySelector('img')?.getAttribute('src')).toBe('/api/assets/upload-test'));
 fireEvent.click(screen.getByRole('button',{name:/完\s*成/,hidden:true}));
 expect(title.textContent).toBe('尚未保存的新标题');
 fireEvent.click(screen.getByRole('button',{name:'保存修改'}));
 await waitFor(()=>expect(mocks.api).toHaveBeenCalledWith('/works/w1','PATCH',expect.objectContaining({title:'尚未保存的新标题',body:'原始正文',image_ids:[image.id],rich_text:expect.objectContaining({body:expect.objectContaining({doc:expect.objectContaining({type:'doc'})})})})));
});
