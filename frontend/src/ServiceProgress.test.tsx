// @vitest-environment jsdom
import React from 'react';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ServiceProgress} from './ServiceProgress';
import {api} from './api';
vi.mock('./api',()=>({api:vi.fn()}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
const state={revision:4,mission:{text:'选一台适合工作的电脑'},tasks:[{id:'v',title:'核实软件兼容情况',kind:'verify',status:'waiting_staff'},
 {id:'u',title:'了解实际工作',kind:'discover',status:'waiting_customer'}]};
it('显示咨询目标和待办，并登记核实结果而非自动完成',async()=>{
 const changed=vi.fn();vi.mocked(api).mockResolvedValue({ok:true});
 render(<ServiceProgress state={state} conversationId="c" editable onChanged={changed}/>);
 expect(screen.getByText('选一台适合工作的电脑')).toBeTruthy();expect(screen.getByText('待客户回复')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'登记结果'}));
 fireEvent.change(screen.getByLabelText('处理结果'),{target:{value:'已核实，可按指定版本安装'}});
 fireEvent.click(screen.getByRole('button',{name:'保存结果'}));
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/conversations/c/service-tasks/v','POST',{revision:4,status:'completed',result:'已核实，可按指定版本安装'}));
 expect(changed).toHaveBeenCalledOnce();
});
it('过期状态不允许处理，完成项默认收起',()=>{
 render(<ServiceProgress state={{...state,tasks:[...state.tasks,{id:'done',kind:'answer',title:'旧事项',status:'completed'}]}} conversationId="c" editable={false}/>);
 expect((screen.getByRole('button',{name:'登记结果'}) as HTMLButtonElement).disabled).toBe(true);
 expect(screen.queryByText('旧事项')).toBeNull();
});
it('客服可开始核实并设置截止时间',async()=>{
 vi.mocked(api).mockResolvedValue({ok:true});
 render(<ServiceProgress state={state} conversationId="c" editable/>);
 fireEvent.click(screen.getByRole('button',{name:'开始核实'}));
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/conversations/c/service-tasks/v','POST',{revision:4,status:'in_progress'}));
 expect(screen.getByRole('button',{name:'调整截止时间'})).toBeTruthy();
});
it('精简详情不展示已处理历史，仍可处理待核实事项',()=>{
 render(<ServiceProgress state={{...state,tasks:[...state.tasks,{id:'done',kind:'answer',title:'旧事项',status:'completed'}]}} conversationId="c" editable showCompleted={false}/>);
 expect(screen.getByRole('button',{name:'登记结果'})).toBeTruthy();
 expect(screen.queryByRole('button',{name:/已处理/})).toBeNull();
});
