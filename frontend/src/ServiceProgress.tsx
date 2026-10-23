import React,{useState} from 'react';
import {Alert,Button,Input,Tag} from 'antd';
import {api,Data,time} from './api';

const labels:Record<string,string>={ready:'待处理',blocked:'等待前置事项',waiting_staff:'待门店核实',in_progress:'核实处理中',waiting_customer:'待客户回复',completed:'已完成',cancelled:'已取消'};
type Props={state:Data;conversationId?:string;editable:boolean;onChanged?:()=>void;showCompleted?:boolean};
export function ServiceProgress({state,conversationId,editable,onChanged,showCompleted=true}:Props){
 const [editing,setEditing]=useState(''),[result,setResult]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[expanded,setExpanded]=useState(false);
 const [deadlineTask,setDeadlineTask]=useState(''),[deadline,setDeadline]=useState('');
 const tasks:Data[]=state.tasks||[],pending=tasks.filter(t=>!['completed','cancelled'].includes(t.status));
 const finished=tasks.filter(t=>['completed','cancelled'].includes(t.status));
 async function save(taskId:string,status:'completed'|'cancelled'){
  if(!result.trim()||!conversationId)return;
  setBusy(true);setError('');
  try{await api(`/conversations/${conversationId}/service-tasks/${taskId}`,'POST',{revision:state.revision,status,result:result.trim()});setEditing('');setResult('');onChanged?.();}
  catch(e){setError(e instanceof Error?e.message:'保存未完成，请重试');}finally{setBusy(false);}
 }
 async function updateTask(task:Data,status:'in_progress'|'waiting_staff',due_at?:string){
  if(!conversationId||busy)return;
  setBusy(true);setError('');
  try{await api(`/conversations/${conversationId}/service-tasks/${task.id}`,'POST',{revision:state.revision,status,...(due_at?{due_at}: {})});setDeadlineTask('');onChanged?.();}
  catch(e){setError(e instanceof Error?e.message:'更新未完成，请重试');}finally{setBusy(false);}
 }
 const visibleMission=state.mission?.source!=='service_policy'?state.mission:null;
 if(!visibleMission&&!pending.length&&(!showCompleted||!finished.length))return null;
 return <section className="service-progress" aria-label="接待进度">
  {visibleMission&&<div className="service-mission"><small>接待目标</small><p>{visibleMission.text}</p></div>}
  {pending.length>0&&<><h4>接下来处理</h4>{pending.map(task=><div className="service-task" key={task.id}>
   <div><span>{task.title}</span><Tag>{labels[task.status]||'待处理'}</Tag></div>
   {task.kind==='verify'&&<><p className="muted">负责人：当前接待客服 · {task.due_at?`截止：${time(task.due_at)}${new Date(task.due_at)<new Date()?' · 已逾期':''}`:'请设置核实截止时间'}</p>
    {task.status==='waiting_staff'&&<Button type="link" size="small" disabled={!editable||busy} onClick={()=>void updateTask(task,'in_progress')}>开始核实</Button>}
    <Button type="link" size="small" disabled={!editable||busy||task.status==='blocked'} onClick={()=>{setDeadlineTask(task.id);setDeadline(task.due_at?new Date(new Date(task.due_at).getTime()+8*3600000).toISOString().slice(0,16):'');}}>调整截止时间</Button>
    {deadlineTask===task.id&&<div><label htmlFor={'deadline-'+task.id}>截止时间（北京时间）</label><input id={'deadline-'+task.id} className="date-input" type="datetime-local" value={deadline} onChange={e=>setDeadline(e.target.value)}/><Button size="small" disabled={!editable||busy||!deadline} onClick={()=>void updateTask(task,task.status==='in_progress'?'in_progress':'waiting_staff',new Date(deadline+'+08:00').toISOString())}>保存截止时间</Button><Button size="small" onClick={()=>setDeadlineTask('')}>收起</Button></div>}
   </>}
   {task.kind==='verify'&&editing!==task.id&&<Button type="link" size="small" disabled={!editable||busy||task.status==='blocked'} onClick={()=>{setEditing(task.id);setResult('');}}>登记结果</Button>}
   {editing===task.id&&<div className="service-task-form"><label htmlFor={'task-result-'+task.id}>处理结果</label><Input.TextArea id={'task-result-'+task.id} value={result} onChange={e=>setResult(e.target.value)} maxLength={1000} autoSize={{minRows:2,maxRows:5}}/><div><Button size="small" type="primary" disabled={!editable||!result.trim()} loading={busy} onClick={()=>void save(task.id,'completed')}>保存结果</Button><Button size="small" disabled={!editable||busy||!result.trim()} onClick={()=>void save(task.id,'cancelled')}>取消事项</Button><Button size="small" type="text" disabled={busy} onClick={()=>setEditing('')}>收起</Button></div></div>}
  </div>)}</>}
  {error&&<Alert type="error" message={error}/>}
  {showCompleted&&finished.length>0&&<><Button size="small" type="text" onClick={()=>setExpanded(v=>!v)} aria-expanded={expanded}>{expanded?'收起已处理':'已处理 '+finished.length+' 项'}</Button>{expanded&&finished.map(task=><p className="muted" key={task.id}>{task.title} · {labels[task.status]}</p>)}</>}
 </section>;
}
