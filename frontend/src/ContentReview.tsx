import React, {useState} from 'react';
import {Alert,Button,Input,Modal,Tag} from 'antd';
import {Data,statuses,time} from './api';
import {SourceNotice} from './CompetitionEvidence';

type Props={work:Data;dirty:boolean;busy?:boolean;error?:string;onCheck:()=>void;onRepair:()=>void;onApprove:(note:string)=>Promise<void>};

export function ContentReview({work,dirty,busy=false,error='',onCheck,onRepair,onApprove}:Props){
 const [open,setOpen]=useState(false),[note,setNote]=useState(''),[saving,setSaving]=useState(false),[approvalError,setApprovalError]=useState('');
 const r=work.report||{},status=dirty?'unchecked':r.status;
 const approved=['passed','manual_passed'].includes(status);
 const issues=r.issues||[],pending=Array.from(new Set<string>([...(work.content.pending||[]),...(r.pending||[])]));
 const blocked=!!r.blocked||issues.some((item:Data)=>item.type==='资料冲突');
 const disabled=dirty||busy||saving;
 const approve=async()=>{
  if(!note.trim()||disabled)return;
  setSaving(true);setApprovalError('');
  try{await onApprove(note.trim());setOpen(false);setNote('');}
  catch(e){setApprovalError((e as Error).message);}
  finally{setSaving(false);}
 };
 const details=<ul className="review-issues">{issues.map((item:Data,i:number)=><li key={'issue'+i}><strong>{item.type}：</strong>{item.text}</li>)}{pending.map(text=><li key={text}><strong>待确认：</strong>{text}</li>)}</ul>;
 return <section className="panel content-status">
  <div className="section-title"><h3>内容状态</h3><Button size="small" disabled={disabled} onClick={onCheck}>重新检查</Button></div>
  <Tag color={approved?'green':status==='needs_review'?'orange':'default'}>{statuses[status]||status}</Tag>
  <SourceNotice content={work.content}/>
  <p className="muted">{dirty?'请先保存修改，再调整或确认。':busy?'正在处理当前版本，请稍候。':approved?'可以复制、正式导出或制作海报。':'可以自动调整，或核实下列信息后人工确认通过。'}</p>
  {error&&<Alert type="error" showIcon message={error}/>}
  {!dirty&&r.approval&&<div className="review-approval"><p>确认人：{r.approval.display_name} · {time(r.approval.approved_at)}</p><p>确认说明：{r.approval.note}</p></div>}
  {!dirty&&(issues.length>0||pending.length>0)&&(status==='manual_passed'?<details className="review-history"><summary>原始检查记录（已人工确认）</summary>{details}</details>:details)}
  {!approved&&<>
   {!dirty&&blocked&&<Alert type="warning" message="资料存在冲突，请核对并重新检查后再人工通过。"/>}
   <div className="review-buttons">
    <Button type="primary" block disabled={disabled} onClick={onRepair}>自动调整并检查</Button>
    <Button block disabled={disabled||blocked} onClick={()=>{setApprovalError('');setOpen(true);}}>人工确认通过</Button>
   </div>
   <p className="muted review-help">自动调整会保存新版本，原稿保留在修改记录中。仍需核实的信息会继续列出。</p>
  </>}
  <Modal title="人工确认通过" open={open} onCancel={()=>!saving&&setOpen(false)} closable={!saving} maskClosable={!saving}
   okText="确认通过当前版本" cancelText="返回核对" confirmLoading={saving} onOk={approve}
   okButtonProps={{disabled:disabled||!note.trim()}} cancelButtonProps={{disabled:saving}}>
   <p>请确认已核对第 {work.version} 版内容及以下检查项。通过后可正式导出，系统将保留原始检查记录和你的确认说明。</p>
   {details}
   <label htmlFor="work-approval-note">确认说明</label>
   <Input.TextArea id="work-approval-note" value={note} onChange={e=>setNote(e.target.value)} rows={3} maxLength={1000} placeholder="例如：已核实门店当日价格，当前表述可以使用。" disabled={saving}/>
   {approvalError&&<Alert type="error" message={approvalError} style={{marginTop:12}}/>}
  </Modal>
 </section>;
}
