import React,{useEffect,useRef} from 'react';
import {App,Button} from 'antd';
import {BellOutlined,ReloadOutlined} from '@ant-design/icons';
import {Data,time} from './api';
import {useData} from './lifecycle';

type Navigate=(view:string,id?:string,taskId?:string)=>void;

function useReminders(){
 const state=useData('/notifications',5000);
 useEffect(()=>{
  const refresh=()=>{void state.refresh();};
  const visible=()=>{if(document.visibilityState==='visible')refresh();};
  window.addEventListener('focus',refresh);
  window.addEventListener('online',refresh);
  window.addEventListener('followups-changed',refresh);
  document.addEventListener('visibilitychange',visible);
  return()=>{
   window.removeEventListener('focus',refresh);
   window.removeEventListener('online',refresh);
   window.removeEventListener('followups-changed',refresh);
   document.removeEventListener('visibilitychange',visible);
  };
 },[state.refresh]);
 return state;
}

export function Notifications({navigate,userId}:{navigate:Navigate;userId:string}){
 const jobs=useData('/jobs',15000),reminders=useReminders();
 const {notification}=App.useApp();
 const seen=useRef(new Set<string>());
 useEffect(()=>{
  if(reminders.data?.length===0)notification.destroy('followup-due-'+userId);
  const fresh=(reminders.data||[]).filter((item:Data)=>{
   const key=`followup-reminded:${userId}:${item.id}:${item.due_at}`;
   if(seen.current.has(key))return false;
   seen.current.add(key);
   try{if(sessionStorage.getItem(key))return false;sessionStorage.setItem(key,'1');}catch{/* Keep in-memory deduplication when storage is unavailable. */}
   return true;
  });
  if(fresh.length)notification.info({
   key:'followup-due-'+userId,message:fresh[0].kind==='verification'?'门店核实到期提醒':'跟进到期提醒',
   description:`${fresh[0].customer_name}：${fresh[0].purpose}${fresh.length>1?`，另有 ${fresh.length-1} 条待办` :fresh[0].kind==='verification'?'，请核实并登记结果。':'，请及时联系并记录结果。'}`,
   btn:<Button type="primary" size="small" onClick={()=>navigate('tasks')}>查看消息</Button>,duration:8,
  });
 },[reminders.data,notification,navigate,userId]);
 useEffect(()=>()=>notification.destroy('followup-due-'+userId),[notification,userId]);
 const count=reminders.data?.length||0;
 const attention=jobs.data?.some((job:Data)=>['queued','running','needs_input','waiting_remote','failed'].includes(job.status));
 const verification=reminders.data?.some((item:Data)=>item.kind==='verification');
 const label=count?`通知与进度，${count}条到期${verification?'待办':'跟进'}`:'通知与进度';
 return <Button className="notifications-button" type="text" aria-label={label} title={label} onClick={()=>navigate('tasks')}>
  <BellOutlined/>{count?<span className="notification-count" aria-hidden="true">{count>99?'99+':count}</span>:attention?<span className="notification-dot" aria-hidden="true"/>:null}
 </Button>;
}

export function FollowupMessages({navigate}:{navigate:Navigate}){
 const {data,error,refresh}=useReminders();
 const verification=(data||[]).filter((item:Data)=>item.kind==='verification');
 const followups=(data||[]).filter((item:Data)=>item.kind!=='verification');
 return <section className="panel followup-messages" aria-labelledby="due-followups-heading">
  <div className="section-title"><h2 id="due-followups-heading">待办提醒</h2><Button size="small" icon={<ReloadOutlined/>} aria-label="刷新跟进提醒" onClick={()=>void refresh()}>刷新</Button></div>
  {error&&<p role="alert">{error}</p>}
  {!data?<p role="status">正在加载跟进提醒…</p>:<>
   <div className="reminder-group"><h3>待核实 · {verification.length}</h3>{verification.length?<ul className="followup-message-list">{verification.map((item:Data)=><li key={item.id}>
    <div><strong>{item.purpose}</strong><p>{item.customer_name} · 会话 {item.conversation_ref||item.conversation_id.slice(-6)}</p><small className={item.status==='awaiting_feedback'?'verification-ready':'verification-overdue'}>{item.status==='awaiting_feedback'?'已核实，待反馈客户':item.status==='in_progress'?'核实中 · 已逾期':'待核实 · 已逾期'} · {time(item.due_at)}</small></div>
    <Button type="primary" ghost aria-label={'处理核实：'+item.purpose} onClick={()=>navigate('chat',item.conversation_id,item.task_id)}>{item.status==='awaiting_feedback'?'反馈客户':'处理核实'}</Button>
   </li>)}</ul>:<p className="muted">暂无到期待核实事项</p>}</div>
   <div className="reminder-group"><h3>购买跟进 · {followups.length}</h3>{followups.length?<ul className="followup-message-list">{followups.map((item:Data)=><li key={item.id}>
    <div><strong>{item.customer_name}</strong><p>{item.purpose}</p><small>计划时间：{time(item.due_at)} · 待处理</small></div>
    <Button type="primary" ghost onClick={()=>navigate('followups',item.id)}>去处理</Button>
   </li>)}</ul>:<p className="muted">暂无到期跟进</p>}</div>
  </>}
 </section>;
}
