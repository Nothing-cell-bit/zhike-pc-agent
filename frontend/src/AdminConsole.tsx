import {SiteAiSettings,SiteKnowledgeSettings,SiteOperations} from './AdminSiteTools';
import {PriceRuleSettings} from './PriceRuleSettings';
import {AdminConversationAllocation} from './AdminConversationAllocation';
import React,{useState} from 'react';
import {Alert,App,Button,Empty,Form,Input,Modal,Spin,Switch,Tag,Tabs} from 'antd';
import {api,Data} from './api';
import {useData} from './lifecycle';
import './adminConsole.css';

type Props={user:Data;section:'website'|'accounts'|'allocation';onNavigate:(view:string)=>void;onLogout:()=>void;onWebsiteSaved?:()=>void};
export function AdminConsole({user,section,onNavigate,onLogout,onWebsiteSaved}:Props){
 return <div className="admin-console">
  <header className="admin-header"><a className="brand" href="/admin"><div className="brand-symbol">知</div><div>知客<span>管理后台</span></div></a><div><span>{user.display_name}</span><Tag>管理员</Tag><Button type="text" onClick={onLogout}>退出登录</Button></div></header>
  <main className="admin-main"><nav className="admin-navigation" aria-label="管理导航">
   <button type="button" className={section==='website'?'selected':''} aria-current={section==='website'?'page':undefined} onClick={()=>onNavigate('admin-website')}>网站设置</button>
   <button type="button" className={section==='accounts'?'selected':''} aria-current={section==='accounts'?'page':undefined} onClick={()=>onNavigate('admin-accounts')}>管理员设置</button>
   <button type="button" className={section==='allocation'?'selected':''} aria-current={section==='allocation'?'page':undefined} onClick={()=>onNavigate('admin-allocation')}>对话分配</button>
  </nav>
  {section==='allocation'?<AdminConversationAllocation onAccounts={()=>onNavigate('admin-accounts')}/>:section==='website'?<WebsiteSettings onSaved={onWebsiteSaved}/>:<AdministratorSettings user={user} onLogout={onLogout}/>}
  </main>
 </div>;
}

function WebsiteSettings({onSaved}:{onSaved?:()=>void}){
 const store=useData('/store'),[saving,setSaving]=useState(false),[error,setError]=useState('');const {message}=App.useApp();
 const save=async(values:Data)=>{
  if(saving)return;setSaving(true);setError('');
  try{await api('/admin/store','PUT',values);message.success('网站设置已保存');onSaved?.();}
  catch(reason){setError((reason as Error).message);}
  finally{setSaving(false);}
 };
 const basic=<section className="admin-card">
  {store.error?<Alert type="error" message={store.error}/>:!store.data?<Spin/>:<Form layout="vertical" initialValues={store.data} onFinish={save}>
   <Form.Item name="name" label="网站名称" rules={[{required:true,message:'请填写网站名称'},{max:60}]}><Input maxLength={60}/></Form.Item>
   <Form.Item name="hours" label="接待时间" rules={[{max:60}]}><Input maxLength={60} placeholder="例如：09:00—21:00"/></Form.Item>
   <Form.Item name="welcome" label="欢迎语" rules={[{max:300}]}><Input.TextArea rows={3} maxLength={300} showCount/></Form.Item>
   {error&&<Alert type="error" message={error}/>}
   <Button aria-label="保存网站设置" type="primary" htmlType="submit" loading={saving}>保存网站设置</Button>
  </Form>}
 </section>;
 return <><div className="admin-page-heading"><h1>网站设置</h1><p>网站信息、AI 配置、知识库及运行维护。</p></div><Tabs className="admin-settings-tabs" items={[{key:'basic',label:'基本信息',children:basic},{key:'ai',label:'AI配置',children:<SiteAiSettings/>},{key:'knowledge',label:'知识库',children:<SiteKnowledgeSettings/>},{key:'pricing',label:'报价规则',children:<PriceRuleSettings/>},{key:'operations',label:'运行维护',children:<SiteOperations/>}]}/></>;
}

function AdministratorSettings({user,onLogout}:{user:Data;onLogout:()=>void}){
 const users=useData('/admin/users'),[dialog,setDialog]=useState<'password'|'staff'|null>(null),[changing,setChanging]=useState(''),[error,setError]=useState('');const {message}=App.useApp();
 const staff=(users.data||[]).filter((item:Data)=>item.role==='staff');
 const toggle=async(item:Data,active:boolean)=>{
  if(changing)return;setChanging(item.id);setError('');
  try{await api('/admin/users/'+item.id,'PATCH',{role:'staff',active});await users.refresh();message.success(active?'客服账号已启用':'客服账号已停用');}
  catch(reason){setError((reason as Error).message);}
  finally{setChanging('');}
 };
 return <><div className="admin-page-heading"><h1>管理员设置</h1><p>管理自己的账号和客服登录权限。</p></div>
  <section className="admin-card admin-personal"><div><h2>管理员账号</h2><p>{user.display_name}<span>登录用户名：{user.username}</span></p></div><Button onClick={()=>setDialog('password')}>修改我的密码</Button></section>
  <section className="admin-card"><div className="admin-card-heading"><div><h2>客服账号</h2><p>由管理员开通，客服使用员工入口登录。</p></div><Button aria-label="新增客服账号" type="primary" onClick={()=>setDialog('staff')}>新增客服账号</Button></div>
   {(users.error||error)&&<Alert type="error" message={users.error||error}/>}
   {!users.data&&!users.error?<Spin/>:!staff.length?<Empty description="还没有客服账号"/>:<div className="admin-account-list">{staff.map((item:Data)=><div className="admin-account-row" key={item.id}><div><strong>{item.display_name}</strong><span>{item.username}</span></div><Tag>{item.active?'已启用':'已停用'}</Tag><Switch aria-label={(item.active?'停用':'启用')+item.display_name} checked={item.active} disabled={!!changing} loading={changing===item.id} onChange={active=>void toggle(item,active)}/></div>)}</div>}
  </section>
  {dialog&&<AdminAccountDialog kind={dialog} onClose={()=>setDialog(null)} onSaved={()=>{setDialog(null);void users.refresh();}} onPasswordChanged={onLogout}/>}
 </>;
}

function AdminAccountDialog({kind,onClose,onSaved,onPasswordChanged}:{kind:'password'|'staff';onClose:()=>void;onSaved:()=>void;onPasswordChanged:()=>void}){
 const [saving,setSaving]=useState(false),[error,setError]=useState('');const {message}=App.useApp();
 const submit=async(values:Data)=>{
  if(saving)return;setSaving(true);setError('');
  try{
   if(kind==='staff'){await api('/admin/users','POST',{...values,role:'staff'});message.success('客服账号已创建');onSaved();}
   else{await api('/auth/password','POST',{old_password:values.old_password,new_password:values.new_password});message.success('密码已更新，请重新登录');onPasswordChanged();}
  }catch(reason){setError((reason as Error).message);}
  finally{setSaving(false);}
 };
 return <Modal open title={kind==='staff'?'创建客服账号':'修改管理员密码'} footer={null} onCancel={onClose} width={460}>
  <Form layout="vertical" onFinish={submit}>
   {kind==='staff'?<>
    <Form.Item name="display_name" label="姓名" rules={[{required:true},{max:40}]}><Input maxLength={40}/></Form.Item>
    <Form.Item name="username" label="登录用户名" rules={[{required:true,pattern:/^[A-Za-z0-9_\-]{3,40}$/,message:'填写3～40位字母、数字、下划线或短横线'}]}><Input autoComplete="off" maxLength={40}/></Form.Item>
    <Form.Item name="password" label="初始密码" rules={[{required:true,min:10,max:128,message:'密码长度为10～128位'}]}><Input.Password autoComplete="new-password" maxLength={128}/></Form.Item>
   </>:<>
    <Form.Item name="old_password" label="当前密码" rules={[{required:true}]}><Input.Password autoComplete="current-password" maxLength={128}/></Form.Item>
    <Form.Item name="new_password" label="新密码" rules={[{required:true,min:10,max:128,message:'密码长度为10～128位'}]}><Input.Password autoComplete="new-password" maxLength={128}/></Form.Item>
    <Form.Item name="confirm_password" label="确认新密码" dependencies={['new_password']} rules={[{required:true},({getFieldValue})=>({validator:(_,value)=>!value||value===getFieldValue('new_password')?Promise.resolve():Promise.reject(new Error('两次密码不一致'))})]}><Input.Password autoComplete="new-password" maxLength={128}/></Form.Item>
   </>}
   {error&&<Alert type="error" message={error}/>}
   <Button aria-label={kind==='staff'?'创建客服账号':'保存新密码'} type="primary" htmlType="submit" block loading={saving}>{kind==='staff'?'创建客服账号':'保存并重新登录'}</Button>
  </Form>
 </Modal>;
}
