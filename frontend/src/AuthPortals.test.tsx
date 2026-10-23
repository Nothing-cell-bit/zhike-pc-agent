// @vitest-environment jsdom
import React from 'react';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {CustomerAuthModal,EmployeeLogin} from './AuthPortals';
import {entryView,loginDestination} from './authRoutes';
const mocks=vi.hoisted(()=>({api:vi.fn()}));
vi.mock('./api',()=>({api:mocks.api}));
beforeEach(()=>vi.stubGlobal('matchMedia',()=>({matches:false,addListener:vi.fn(),removeListener:vi.fn(),addEventListener:vi.fn(),removeEventListener:vi.fn()})));
afterEach(()=>{cleanup();vi.clearAllMocks();vi.unstubAllGlobals();});

function fill(){
 fireEvent.change(screen.getByLabelText('用户名'),{target:{value:'test_user'}});
 fireEvent.change(screen.getByLabelText('密码'),{target:{value:'TestPortalPassword123'}});
}

it('员工入口只有登录，注明由管理员创建，并调用员工登录接口',async()=>{
 const user={id:'s1',role:'staff'},signedIn=vi.fn();mocks.api.mockResolvedValue(user);
 render(<EmployeeLogin onAuthenticated={signedIn} onBack={vi.fn()}/>);
 expect(screen.getByRole('heading',{name:'员工登录'})).toBeTruthy();
 expect(screen.getByText(/账号由门店管理员创建/)).toBeTruthy();
 expect(screen.queryByRole('button',{name:/注册/})).toBeNull();
 fill();fireEvent.click(screen.getByRole('button',{name:'登录工作台'}));
 await waitFor(()=>expect(mocks.api).toHaveBeenCalledWith('/auth/staff/login','POST',{username:'test_user',password:'TestPortalPassword123'}));
 expect(signedIn).toHaveBeenCalledWith(user);
});

it('客户登录和注册使用客户接口，注册没有角色选择',async()=>{
 const signedIn=vi.fn(),switchMode=vi.fn();mocks.api.mockResolvedValue({id:'c1',role:'customer'});
 const view=render(<CustomerAuthModal open mode="login" onClose={vi.fn()} onModeChange={switchMode} onAuthenticated={signedIn}/>);
 fill();fireEvent.click(screen.getByRole('button',{name:'客户登录'}));
 await waitFor(()=>expect(mocks.api).toHaveBeenCalledWith('/auth/customer/login','POST',expect.any(Object)));
 view.rerender(<CustomerAuthModal open mode="register" onClose={vi.fn()} onModeChange={switchMode} onAuthenticated={signedIn}/>);
 fill();fireEvent.change(screen.getByLabelText('昵称'),{target:{value:'测试客户'}});
 expect(screen.queryByText('客服')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'注册并保留咨询'}));
 await waitFor(()=>expect(mocks.api).toHaveBeenCalledWith('/auth/register','POST',{username:'test_user',password:'TestPortalPassword123',display_name:'测试客户'}));
});

it('登录失败保留表单并显示入口提示，不跳转到工作台',async()=>{
 const signedIn=vi.fn();mocks.api.mockRejectedValue(new Error('该账号为客户账号，请使用客户登录入口'));
 render(<EmployeeLogin onAuthenticated={signedIn} onBack={vi.fn()}/>);
 fill();fireEvent.click(screen.getByRole('button',{name:'登录工作台'}));
 await screen.findByText('该账号为客户账号，请使用客户登录入口');
 expect(signedIn).not.toHaveBeenCalled();
 expect((screen.getByLabelText('用户名') as HTMLInputElement).value).toBe('test_user');
});

it('直接访问员工地址按会话角色分流，登录后也按角色跳转',()=>{
 for(const path of ['/staff','/staff/login']){
  expect(entryView(path)).toBe('staff-login');expect(entryView(path,'customer')).toBe('staff-login');
  expect(entryView(path,'staff')).toBe('dashboard');expect(entryView(path,'admin')).toBe('admin-website');
 }
 expect(entryView('/','staff')).toBe('customer');
 expect(loginDestination('customer')).toBe('customer');expect(loginDestination('admin')).toBe('admin-website');
});
