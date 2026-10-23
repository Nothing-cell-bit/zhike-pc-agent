// @vitest-environment jsdom
import React from 'react';
import {ConfigProvider} from 'antd';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {VerificationDesk} from './VerificationDesk';
import {api} from './api';
vi.mock('./api',()=>({api:vi.fn(),time:(s:string)=>s}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
const task={id:'v',kind:'verify',title:'核实 Blender 适配性',status:'waiting_staff',evidence:{quote:'Blender 中等建模够用吗？'},result:''};
const base={open:true,onClose:vi.fn(),conversationId:'c',customerName:'演示客户',state:{revision:4,action:{},tasks:[task]},editable:true,updating:false,analysisFailed:false,currentReply:true,onChanged:vi.fn(),onJob:vi.fn(),onRetry:vi.fn(),onAdopt:vi.fn()};
const show=(p={})=>render(<ConfigProvider theme={{token:{motion:false}}}><VerificationDesk {...base} {...p}/></ConfigProvider>);

it('直接定位核实事项，显示客户原话并按结论登记，保存后等待生成而非自动发送',async()=>{
 vi.mocked(api).mockResolvedValue({ok:true,job_id:'j'});show();
 expect(screen.getByText('Blender 中等建模够用吗？')).toBeTruthy();
 fireEvent.change(screen.getByLabelText('核实结论'),{target:{value:'conditional'}});
 fireEvent.change(screen.getByLabelText('结论说明'),{target:{value:'指定场景已测试通过'}});
 fireEvent.change(screen.getByLabelText('适用条件与限制'),{target:{value:'仅限 Windows 11 和指定场景'}});
 fireEvent.change(screen.getByLabelText('核实依据'),{target:{value:'门店样机测试记录 TEST-001'}});
 fireEvent.click(screen.getByRole('button',{name:'保存并生成客户回复'}));
 await waitFor(()=>expect(base.onJob).toHaveBeenCalledWith('j'));
 expect(vi.mocked(api).mock.calls[0][2]).toMatchObject({revision:4,status:'completed',verification:{conclusion:'conditional',source:'门店样机测试记录 TEST-001'}});
 expect(base.onAdopt).not.toHaveBeenCalled();
});

it('暂未确认必须填写下次处理时间，不能伪装已完成',async()=>{
 show();fireEvent.change(screen.getByLabelText('核实结论'),{target:{value:'unconfirmed'}});
 fireEvent.change(screen.getByLabelText('结论说明'),{target:{value:'样机缺少插件，需补测'}});
 fireEvent.change(screen.getByLabelText('下次处理时间（北京时间）'),{target:{value:''}});
 expect((screen.getByRole('button',{name:'保留待办并安排下次核实'}) as HTMLButtonElement).disabled).toBe(true);
 expect(screen.getByLabelText('下次处理时间（北京时间）')).toBeTruthy();
});

it('已核实仅展示该任务对应的当前候选，采用后仍需客服发送',()=>{
 const adopt=vi.fn();show({onAdopt:adopt,state:{revision:5,tasks:[{...task,status:'completed',result:'指定场景可用',feedback_status:'pending'}],action:{kind:'inform',candidates:[{id:'wrong',reply:'无关建议',verification_ids:['other']},{id:'right',reply:'指定场景可以用，接下来确认预算。',verification_ids:['v']}]}}});
 expect(screen.queryByText('无关建议')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'采用回复并返回会话'}));
 expect(adopt).toHaveBeenCalledWith('指定场景可以用，接下来确认预算。','right');
});
