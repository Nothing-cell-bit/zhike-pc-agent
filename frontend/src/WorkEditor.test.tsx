// @vitest-environment jsdom
import React from 'react';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import WorkEditor from './WorkEditor';
const mocks=vi.hoisted(()=>({api:vi.fn(),fieldChange:null as any}));
vi.mock('./api',async original=>({...await original<typeof import('./api')>(),api:mocks.api}));
vi.mock('./RichBodyEditor',()=>({RichTextField:(props:any)=><textarea aria-label={props.label} value={props.value} onChange={event=>mocks.fieldChange?.({[props.field]:event.target.value})}/>,RichBodyEditor:React.forwardRef((props:any,ref:any)=>{mocks.fieldChange=props.onChange;return <>{props.children}<textarea aria-label="正文" value={props.body} onChange={event=>props.onChange({body:event.target.value,images:props.images})}/>{props.footer}</>;})}));
vi.mock('./AiPosterStudio',()=>({AiPosterStudio:()=> <div>AI海报工具内容</div>}));
const work={id:'w1',version:1,brief:{platform:'公众号',product_id:'p1',audience:'大学生',scene:'学习和编程'},content:{product_name:'MateBook D 14',title:'大学生选电脑',intro:'开学选本建议',body:'第一段正文',cta:'欢迎到店体验',tags:[],pending:['软件兼容性待确认'],images:[]},report:{status:'needs_review',pending:['软件兼容性待确认'],issues:[]},versions:[],available_images:[]};
const ctx={id:'w1',onBack:vi.fn(),products:[{id:'p1',name:'MateBook D 14'}],navigate:vi.fn(),modal:{confirm:vi.fn(),info:vi.fn()},action:async(fn:any)=>fn(),watch:vi.fn()};
afterEach(()=>{cleanup();vi.clearAllMocks();});
it('朋友圈编辑页直接显示已生成九宫格，不必打开工具或预览',async()=>{
 const album={id:'g1',work_version:1,items:Array.from({length:9},(_,index)=>({asset_id:'a'+index,url:'/api/assets/a'+index,title:'学习配图'+index}))};
 mocks.api.mockImplementation(async(path:string)=>path.endsWith('/moments-gallery')?{gallery:album}:{...work,brief:{...work.brief,platform:'朋友圈'}});
 render(<WorkEditor {...ctx} modal={ctx.modal as any}/>);
 await screen.findByLabelText('正文');
 await screen.findByLabelText('9张朋友圈配图');
 expect(screen.getAllByAltText(/学习配图/)).toHaveLength(9);
 expect(screen.getByRole('button',{name:'管理朋友圈配图'})).toBeTruthy();
});
it('打开即能直接写正文，检查和海报按需打开',async()=>{
 mocks.api.mockResolvedValue(work);render(<WorkEditor {...ctx} modal={ctx.modal as any}/>);
 await screen.findByLabelText('正文');expect(screen.getByLabelText('作品标题').getAttribute('value')||screen.getByLabelText('作品标题').textContent).toContain('大学生选电脑');
 expect(screen.queryByText('AI海报工具内容')).toBeNull();expect(screen.queryByRole('button',{name:'自动调整并检查'})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:/检查内容/}));
 await screen.findByRole('button',{name:'自动调整并检查'});
});
it('工具弹窗中提供AI海报，编辑区不保留旧预览与编辑切换',async()=>{
 mocks.api.mockResolvedValue(work);render(<WorkEditor {...ctx} modal={ctx.modal as any}/>);
 await screen.findByLabelText('正文');expect(screen.queryByRole('button',{name:'编辑内容'})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'创作工具'}));await screen.findByText('AI海报工具内容');
});
it('直接修改标题后保存，继续使用原有版本校验接口',async()=>{
 mocks.api.mockImplementation(async(path:string,method:string)=>method==='PATCH'?{ok:true}:{...work,version:path.includes('w1')&&mocks.api.mock.calls.some(call=>call[1]==='PATCH')?2:1});
 render(<WorkEditor {...ctx} modal={ctx.modal as any}/>);const title=await screen.findByLabelText('作品标题');
 fireEvent.change(title,{target:{value:'修改后的标题'}});fireEvent.click(screen.getByRole('button',{name:'保存修改'}));
 await waitFor(()=>expect(mocks.api).toHaveBeenCalledWith('/works/w1','PATCH',expect.objectContaining({title:'修改后的标题',expected_version:1})));
});
