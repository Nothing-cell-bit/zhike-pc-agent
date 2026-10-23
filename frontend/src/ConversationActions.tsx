import React,{useState} from 'react';
import {Button} from 'antd';
import {api,Data} from './api';

type Props={
 conversation:Data;userId:string;
 action:(fn:()=>Promise<any>)=>Promise<any>;
 confirm:(options:{title:string;content:string;onOk:()=>Promise<any>})=>unknown;
 onChanged:()=>unknown;onAbandoned:()=>unknown;
};

export function ConversationActions({conversation:c,userId,action,confirm,onChanged,onAbandoned}:Props){
 const [busy,setBusy]=useState(false);
 const owned=c.owner_id===userId;
 const change=async(path:string,body?:unknown)=>{
  setBusy(true);
  try{await action(async()=>{await api(`/conversations/${c.id}/${path}`,'POST',body);window.dispatchEvent(new Event('followups-changed'));await onChanged();});}
  finally{setBusy(false);}
 };
 const abandon=async()=>{
  setBusy(true);
  try{await action(async()=>{
   await api(`/conversations/${c.id}/abandon`,'POST',{expected_owner:c.owner_id});
   window.dispatchEvent(new Event('followups-changed'));await onAbandoned();
  });}finally{setBusy(false);}
 };
 return <div className="contact-actions">
  {!c.owner_id?<Button type="primary" disabled={busy} onClick={()=>void change('claim')}>认领会话</Button>:!owned?
   <Button disabled={busy} onClick={()=>confirm({title:'接管此会话？',content:'接管后由你负责回复客户。',onOk:()=>change('takeover',{expected_owner:c.owner_id})})}>接管会话</Button>:
   <Button disabled={busy} onClick={()=>action(async()=>{await api('/conversations/'+c.id,'PATCH',{status:c.status==='closed'?'active':'closed'});await onChanged();})}>{c.status==='closed'?'重新打开':'结束接待'}</Button>}
  {!c.owner_id&&c.status==='waiting'&&<Button danger disabled={busy} title="从我的列表移除" onClick={()=>void abandon()}>放弃会话</Button>}
 </div>;
}
