import React,{useEffect,useRef,useState} from 'react';
import {Alert,Button,Form,Input,Modal} from 'antd';
import {ArrowLeftOutlined,LockOutlined} from '@ant-design/icons';
import {api,Data} from './api';
import './authPortals.css';

export type CustomerAuthMode='login'|'register';
type Success={onAuthenticated:(user:Data)=>void};

function AccountForm({portal,mode,onAuthenticated}:{portal:'customer'|'staff';mode:CustomerAuthMode}&Success){
 const [loading,setLoading]=useState(false),[error,setError]=useState('');
 const inFlight=useRef(false),mounted=useRef(true);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
 const submit=async(values:Data)=>{
  if(inFlight.current)return;inFlight.current=true;setLoading(true);setError('');
  const path=mode==='register'?'/auth/register':'/auth/'+portal+'/login';
  const credentials={username:values.username,password:values.password,...(mode==='register'?{display_name:values.display_name||''}:{})};
  try{const user=await api(path,'POST',credentials);if(mounted.current)onAuthenticated(user);}
  catch(reason){if(mounted.current)setError((reason as Error).message);}
  finally{inFlight.current=false;if(mounted.current)setLoading(false);}
 };
 return <Form layout="vertical" onFinish={submit} className="account-login-form">
  {error&&<Alert type="error" showIcon message={error}/>}
  <Form.Item name="username" label="用户名" rules={[{required:true,pattern:/^[A-Za-z0-9_\-]{3,40}$/,message:'请输入3～40位字母、数字、下划线或短横线'}]}><Input autoComplete="username" placeholder={portal==='staff'?'管理员分配的员工账号':'请输入客户账号'}/></Form.Item>
  {mode==='register'&&<Form.Item name="display_name" label="昵称"><Input maxLength={40} placeholder="顾问怎么称呼你？" autoComplete="nickname"/></Form.Item>}
  <Form.Item name="password" label="密码" rules={[{required:true,min:10,max:128,message:'密码长度为10～128位'}]}><Input.Password autoComplete={mode==='register'?'new-password':'current-password'} maxLength={128}/></Form.Item>
  <Button block type="primary" htmlType="submit" loading={loading}>{portal==='staff'?'登录工作台':mode==='register'?'注册并保留咨询':'客户登录'}</Button>
 </Form>;
}

export function CustomerAuthModal({open,mode,onClose,onModeChange,onAuthenticated}:{open:boolean;mode:CustomerAuthMode;onClose:()=>void;onModeChange:(mode:CustomerAuthMode)=>void}&Success){
 if(!open)return null;
 return <Modal open title={mode==='register'?'客户注册':'客户登录'} footer={null} onCancel={onClose} width={440}>
  <p className="account-form-description">{mode==='register'?'创建客户账号，保留当前咨询，之后可继续查看自己的咨询记录。':'登录客户账号，继续咨询或查看自己的咨询记录。'}</p>
  <AccountForm key={mode} portal="customer" mode={mode} onAuthenticated={onAuthenticated}/>
  <Button block type="link" onClick={()=>onModeChange(mode==='login'?'register':'login')}>{mode==='login'?'还没有客户账号？注册':'已有客户账号？登录'}</Button>
 </Modal>;
}

export function EmployeeLogin({onAuthenticated,onBack}:{onBack:()=>void}&Success){
 return <div className="employee-login-page">
  <header className="employee-login-header"><a className="brand" href="/"><div className="brand-symbol">知</div><div>知客<span>门店增长工作台</span></div></a><Button type="text" icon={<ArrowLeftOutlined/>} onClick={onBack}>返回客户首页</Button></header>
  <main className="employee-login-main"><section className="employee-login-card" aria-label="员工登录区">
   <div className="employee-login-icon"><LockOutlined/></div><h1>员工登录</h1><p className="account-form-description">客服进入接待工作台，管理员进入网站与账号管理。</p>
   <AccountForm portal="staff" mode="login" onAuthenticated={onAuthenticated}/>
   <div className="employee-account-help">员工账号由门店管理员创建。如需开通或找回账号，请联系管理员。</div>
  </section></main>
 </div>;
}
