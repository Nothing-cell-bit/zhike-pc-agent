// @vitest-environment jsdom
import React from 'react';
import {App} from 'antd';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {AdminConsole} from './AdminConsole';
import {entryView,loginDestination,navigationForRole,viewPath} from './authRoutes';
const mocks=vi.hoisted(()=>({api:vi.fn(),paths:[] as string[],refresh:vi.fn()}));
vi.mock('./api',()=>({api:mocks.api}));
vi.mock('./AdminSiteTools',()=>({SiteAiSettings:()=> <div>AI配置区域</div>,SiteKnowledgeSettings:()=> <div>知识库区域</div>,SiteOperations:()=> <div>运行维护区域</div>}));
vi.mock('./PriceRuleSettings',()=>({PriceRuleSettings:()=> <div>报价规则区域</div>}));
vi.mock('./lifecycle',()=>({useData:(path:string)=>{mocks.paths.push(path);return {data:path==='/store'?{name:'测试门店',hours:'09:00—21:00',welcome:'欢迎咨询'}:[{id:'staff1',username:'worker_one',display_name:'客服甲',role:'staff',active:true}],error:'',refresh:mocks.refresh};}}));
const user={id:'admin1',username:'admin',display_name:'门店管理员',role:'admin'};
beforeEach(()=>vi.stubGlobal('matchMedia',()=>({matches:false,addListener:vi.fn(),removeListener:vi.fn(),addEventListener:vi.fn(),removeEventListener:vi.fn()})));
afterEach(()=>{cleanup();vi.clearAllMocks();vi.unstubAllGlobals();mocks.paths=[];});
const show=(section:'website'|'accounts'='website',onLogout=vi.fn())=>render(<App><AdminConsole user={user} section={section} onNavigate={vi.fn()} onLogout={onLogout}/></App>);

it('管理员默认进入网站设置，业务路由不能把管理员带回客服工作台',()=>{
 expect(loginDestination('admin')).toBe('admin-website');expect(entryView('/staff','admin')).toBe('admin-website');
 expect(entryView('/admin/accounts','admin')).toBe('admin-accounts');expect(viewPath('admin-accounts')).toBe('/admin/accounts');
 for(const route of ['dashboard','chat','works','products','tasks','settings'])expect(navigationForRole('admin',route)).toBe('admin-website');
 expect(navigationForRole('staff','chat')).toBe('chat');expect(navigationForRole('staff','admin-accounts')).toBe('dashboard');
 expect(entryView('/admin/conversations','admin')).toBe('admin-allocation');expect(viewPath('admin-allocation')).toBe('/admin/conversations');
});

it('基本信息默认展开，AI等原设置可通过分类进入，业务工作台入口不出现',async()=>{
 show();expect(screen.getByRole('navigation',{name:'管理导航'})).toBeTruthy();
 expect(screen.getByRole('button',{name:'网站设置'})).toBeTruthy();expect(screen.getByRole('button',{name:'管理员设置'})).toBeTruthy();
 expect(screen.getByRole('button',{name:'对话分配'})).toBeTruthy();
 for(const text of ['客户接待','营销内容','产品资料','门店报价规则','服务连接','产品知识底座','运行任务与恢复','操作记录'])expect(screen.queryByText(text)).toBeNull();
 expect(new Set(mocks.paths)).toEqual(new Set(['/store']));
 fireEvent.click(screen.getByRole('tab',{name:'AI配置'}));await screen.findByText('AI配置区域');
});

it('网站设置沿用现有保存接口',async()=>{
 mocks.api.mockResolvedValue({ok:true});show();
 fireEvent.change(screen.getByLabelText('网站名称'),{target:{value:'更新后的门店'}});
 fireEvent.click(screen.getByRole('button',{name:'保存网站设置'}));
 await waitFor(()=>expect(mocks.api).toHaveBeenCalledWith('/admin/store','PUT',{name:'更新后的门店',hours:'09:00—21:00',welcome:'欢迎咨询'}));
});

it('管理员设置保留个人密码和客服开通，新账号固定为客服',async()=>{
 mocks.api.mockResolvedValue({ok:true});show('accounts');
 expect(screen.getByText('worker_one')).toBeTruthy();expect(screen.getByRole('button',{name:'修改我的密码'})).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'新增客服账号'}));
 fireEvent.change(screen.getByLabelText('姓名'),{target:{value:'客服乙'}});
 fireEvent.change(screen.getByLabelText('登录用户名'),{target:{value:'worker_two'}});
 fireEvent.change(screen.getByLabelText('初始密码'),{target:{value:'TestEmployeePassword123'}});
 fireEvent.click(screen.getByRole('button',{name:'创建客服账号'}));
 await waitFor(()=>expect(mocks.api).toHaveBeenCalledWith('/admin/users','POST',{display_name:'客服乙',username:'worker_two',password:'TestEmployeePassword123',role:'staff'}));
 expect(mocks.paths.every(path=>path==='/admin/users')).toBe(true);
});

it('修改密码先确认一致，成功后要求重新登录',async()=>{
 const logout=vi.fn();mocks.api.mockResolvedValue({ok:true});show('accounts',logout);
 fireEvent.click(screen.getByRole('button',{name:'修改我的密码'}));
 fireEvent.change(screen.getByLabelText('当前密码'),{target:{value:'OldAdminPassword123'}});
 fireEvent.change(screen.getByLabelText('新密码'),{target:{value:'NewAdminPassword123'}});
 fireEvent.change(screen.getByLabelText('确认新密码'),{target:{value:'DifferentPassword123'}});
 fireEvent.click(screen.getByRole('button',{name:'保存新密码'}));await screen.findByText('两次密码不一致');
 expect(mocks.api).not.toHaveBeenCalled();
 fireEvent.change(screen.getByLabelText('确认新密码'),{target:{value:'NewAdminPassword123'}});
 fireEvent.click(screen.getByRole('button',{name:'保存新密码'}));
 await waitFor(()=>expect(mocks.api).toHaveBeenCalledWith('/auth/password','POST',{old_password:'OldAdminPassword123',new_password:'NewAdminPassword123'}));
 await waitFor(()=>expect(logout).toHaveBeenCalled());
});

it('客服启停沿用账号权限接口，不改动角色',async()=>{
 mocks.api.mockResolvedValue({ok:true});show('accounts');
 fireEvent.click(screen.getByRole('switch',{name:'停用客服甲'}));
 await waitFor(()=>expect(mocks.api).toHaveBeenCalledWith('/admin/users/staff1','PATCH',{role:'staff',active:false}));
});
