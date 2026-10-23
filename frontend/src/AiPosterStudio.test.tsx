// @vitest-environment jsdom
import React from 'react';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {AiPosterStudio} from './AiPosterStudio';
import {ApiError} from './api';

const mock=vi.hoisted(()=>({api:vi.fn(),refresh:vi.fn(),jobs:[] as any[],assets:[] as any[]}));
vi.mock('./api',async importOriginal=>({...await importOriginal<typeof import('./api')>(),api:mock.api,requestId:()=> 'poster-unique-request',time:()=> '刚刚',statuses:{queued:'排队中',running:'生成中',completed:'已完成',failed:'失败',waiting_remote:'仍在生成'}}));
vi.mock('./lifecycle',()=>({useData:(path:string)=>({data:path==='/jobs'?mock.jobs:mock.assets,error:'',refresh:mock.refresh})}));
afterEach(()=>{cleanup();vi.clearAllMocks();mock.jobs=[];mock.assets=[];});
const props={work:{id:'work1',version:2,brief:{scene:'学习和写代码'},report:{status:'passed'}},imageId:'image1',dirty:false};
it('提交产品图和场景生成整张海报，不提供模板风格或背景合成入口',async()=>{
 mock.api.mockResolvedValue({job_id:'job1'});render(<AiPosterStudio {...props}/>);
 expect(screen.queryByText('海报风格')).toBeNull();expect(screen.queryByRole('button',{name:'生成背景'})).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'AI设计整张海报'}));
 await waitFor(()=>expect(mock.api).toHaveBeenCalledWith('/works/work1/poster-tasks','POST',{image_id:'image1',expected_version:2,scene:'学习和写代码',ratio:'3:4',request_id:'poster-unique-request'}));
});
it('未保存、未通过检查或没有产品图时禁止生成',()=>{
 const {rerender}=render(<AiPosterStudio {...props} dirty/>);
 expect((screen.getByRole('button',{name:'AI设计整张海报'}) as HTMLButtonElement).disabled).toBe(true);
 rerender(<AiPosterStudio {...props} imageId=""/>);
 expect((screen.getByRole('button',{name:'AI设计整张海报'}) as HTMLButtonElement).disabled).toBe(true);
});
it('刷新后显示已有AI成图并保留原任务续查入口',()=>{
 mock.jobs=[{id:'job1',kind:'poster',target_id:'work1',status:'waiting_remote',remote_id:'remote1'}];
 mock.assets=[{id:'asset1',kind:'ai_poster',metadata_json:{work_id:'work1',work_version:2,ratio:'3:4'}}];
 render(<AiPosterStudio {...props}/>);
 expect(screen.getByRole('button',{name:'继续查看原任务'})).toBeTruthy();
 expect(screen.getByAltText('AI设计的产品海报').getAttribute('src')).toBe('/api/assets/asset1');
 expect((screen.getByRole('button',{name:'AI设计整张海报'}) as HTMLButtonElement).disabled).toBe(true);
});
it('网络提交状态未知时复用原请求，避免重复付费生成',async()=>{
 mock.api.mockRejectedValueOnce(new TypeError('网络中断')).mockResolvedValueOnce({job_id:'job1'});
 render(<AiPosterStudio {...props}/>);
 fireEvent.click(screen.getByRole('button',{name:'AI设计整张海报'}));
 await waitFor(()=>expect(screen.getByText(/不会创建第二个生成任务/)).toBeTruthy());
 expect((screen.getByLabelText('使用场景与创意要求') as HTMLTextAreaElement).disabled).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'AI设计整张海报'}));
 await waitFor(()=>expect(mock.api).toHaveBeenCalledTimes(2));
 expect(mock.api.mock.calls[1][2]).toEqual(mock.api.mock.calls[0][2]);
});
it('明确拒绝的输入可以修正场景后重新提交',async()=>{
 mock.api.mockRejectedValueOnce(new ApiError('场景不完整',422)).mockResolvedValueOnce({job_id:'job1'});
 render(<AiPosterStudio {...props}/>);
 fireEvent.click(screen.getByRole('button',{name:'AI设计整张海报'}));
 await waitFor(()=>expect(screen.getByText('场景不完整')).toBeTruthy());
 fireEvent.change(screen.getByLabelText('使用场景与创意要求'),{target:{value:'图书馆学习与编程'}});
 fireEvent.click(screen.getByRole('button',{name:'AI设计整张海报'}));
 await waitFor(()=>expect(mock.api).toHaveBeenCalledTimes(2));
 expect(mock.api.mock.calls[1][2].scene).toBe('图书馆学习与编程');
});
it('显示真实设计方案与视觉检查结果，不能把未检查的海报显示为通过',()=>{
 mock.assets=[{id:'asset1',kind:'ai_poster',metadata_json:{work_id:'work1',work_version:2,ratio:'3:4',design_engine:'OpenDesign',
   design_spec:{composition_notes:'阳光校园书桌，型号和标题分层'},review:{verdict:'revise',score:.65,review_state:'completed',summary:'标题需要增大',
    issues:[{severity:'medium',description:'右上角标题偏小'}]}}}];
 render(<AiPosterStudio {...props}/>);
 expect(screen.getByText('AI检查后仍需调整')).toBeTruthy();
 expect(screen.getByText('阳光校园书桌，型号和标题分层')).toBeTruthy();
 expect(screen.getByText('右上角标题偏小')).toBeTruthy();
});
