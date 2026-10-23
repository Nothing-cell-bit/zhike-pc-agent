// @vitest-environment jsdom
import React from 'react';
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {Notifications,FollowupMessages} from './Notifications';

const {notify}=vi.hoisted(()=>({notify:vi.fn()}));
const {notificationApi}=vi.hoisted(()=>({notificationApi:{info:notify,destroy:vi.fn()}}));
vi.mock('antd',async()=>({...await vi.importActual<typeof import('antd')>('antd'),App:{useApp:()=>({notification:notificationApi})}}));
const reminder={id:'followup-1',kind:'followup',conversation_id:'conversation-1',customer_name:'林同学',purpose:'确认到店安排',due_at:'2026-10-20T02:00:00Z'};
let reminders:typeof reminder[]=[];
beforeEach(()=>{
 reminders=[];sessionStorage.clear();notify.mockClear();
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>({ok:true,json:async()=>url.endsWith('/notifications')?reminders:[]})));
});
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.useRealTimers();});

it('到期后轮询显示消息数量并提示，刷新组件不重复弹出',async()=>{
 vi.useFakeTimers();const navigate=vi.fn();
 const view=render(<Notifications navigate={navigate} userId="staff-1"/>);
 await act(async()=>{});
 expect(notify).not.toHaveBeenCalled();
 reminders=[reminder];
 await act(async()=>{await vi.advanceTimersByTimeAsync(5000);});
 expect(screen.getByRole('button',{name:'通知与进度，1条到期跟进'})).toBeTruthy();
 expect(notify).toHaveBeenCalledTimes(1);
 fireEvent.click(screen.getByRole('button',{name:'通知与进度，1条到期跟进'}));
 expect(navigate).toHaveBeenCalledWith('tasks');
 await act(async()=>{await vi.advanceTimersByTimeAsync(10000);});
 view.unmount();render(<Notifications navigate={navigate} userId="staff-1"/>);
 await act(async()=>{});
 expect(notify).toHaveBeenCalledTimes(1);
 reminders=[];
 await act(async()=>{window.dispatchEvent(new Event('followups-changed'));});
 expect(screen.queryByRole('button',{name:/1条到期/})).toBeNull();
});

it('消息展示客户、目的和处理入口，断线恢复后仍能获取待办',async()=>{
 reminders=[reminder];const navigate=vi.fn();render(<FollowupMessages navigate={navigate}/>);
 await screen.findByText('林同学');expect(screen.getByText('确认到店安排')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'去处理'}));expect(navigate).toHaveBeenCalledWith('followups','followup-1');
 reminders=[];
 await act(async()=>{window.dispatchEvent(new Event('focus'));});
 await screen.findByText('暂无到期跟进');
});

it('提醒加载失败时明确提示并可重试',async()=>{
 vi.mocked(fetch).mockResolvedValueOnce({ok:false,status:503,json:async()=>({detail:'暂时无法连接'})} as Response);
 render(<FollowupMessages navigate={vi.fn()}/>);
 await screen.findByText('暂时无法连接');
 fireEvent.click(screen.getByRole('button',{name:'刷新跟进提醒'}));
 await screen.findByText('暂无到期跟进');
});

it('核实与购买跟进分组，核实入口携带准确任务定位',async()=>{
 reminders=[reminder,{...reminder,id:'verify:c1:v1',kind:'verification',conversation_id:'c1',task_id:'v1',purpose:'核实 Blender 适配性',status:'waiting_staff'} as typeof reminder];
 const navigate=vi.fn();render(<FollowupMessages navigate={navigate}/>);
 await screen.findByRole('heading',{name:'待核实 · 1'});
 expect(screen.getByRole('heading',{name:'购买跟进 · 1'})).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'处理核实：核实 Blender 适配性'}));
 expect(navigate).toHaveBeenCalledWith('chat','c1','v1');
});

it('重新安排的同一跟进再次到期会提示，客服之间的提示独立',async()=>{
 reminders=[reminder];const view=render(<Notifications navigate={vi.fn()} userId="staff-1"/>);
 await waitFor(()=>expect(notify).toHaveBeenCalledTimes(1));
 reminders=[{...reminder,due_at:'2026-10-21T02:00:00Z'}];
 await act(async()=>{window.dispatchEvent(new Event('followups-changed'));});
 await waitFor(()=>expect(notify).toHaveBeenCalledTimes(2));
 view.unmount();render(<Notifications navigate={vi.fn()} userId="staff-2"/>);
 await waitFor(()=>expect(notify).toHaveBeenCalledTimes(3));
});
