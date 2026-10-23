import React,{useState} from 'react';
import {Alert,Button,Input,Modal} from 'antd';
import {api} from './api';
export function QualificationCheck({conversationId,codes,disabled,onSaved}:{conversationId:string;codes:string[];disabled:boolean;onSaved:()=>void}){
 const [open,setOpen]=useState(false),[proof,setProof]=useState(''),[until,setUntil]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 if(!codes.length)return null;
 return <><Button size="small" block disabled={disabled} onClick={()=>setOpen(true)}>核验优惠资格</Button><Modal title="核验优惠资格" open={open} footer={null} onCancel={()=>setOpen(false)}>
 <p>资格项目：{codes[0]}</p><p className="muted">请先按门店规则核验，仅登记凭据引用，不填写证件原文。</p>
 <form onSubmit={async e=>{e.preventDefault();setBusy(true);setError('');try{await api('/conversations/'+conversationId+'/qualifications','POST',{qualification:codes[0],evidence_ref:proof,valid_until:new Date(until+'+08:00').toISOString()});setOpen(false);setProof('');onSaved();}catch(error){setError((error as Error).message);}finally{setBusy(false);}}}>
 <label htmlFor="qualification-evidence">核验凭据引用</label><Input id="qualification-evidence" required value={proof} onChange={e=>setProof(e.target.value)} maxLength={500}/>
 <label htmlFor="qualification-until">有效截至时间（北京时间）</label><input id="qualification-until" className="date-input" type="datetime-local" required value={until} onChange={e=>setUntil(e.target.value)}/>
 {error&&<Alert type="error" message={error}/>}<Button htmlType="submit" type="primary" loading={busy}>确认已核验</Button>
 </form></Modal></>;
}
