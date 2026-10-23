import React,{useState} from 'react';
import {Alert,Button,Input,Modal,Tag} from 'antd';
import {api,Data,time} from './api';
import {candidateReply} from './DialoguePlan';
import {ChatMessageContent} from './ChatMessageContent';

export const needsVerificationFeedback=(task:Data)=>task.kind==='verify'&&task.status!=='cancelled'&&(task.status!=='completed'||task.feedback_status!=='sent');
const taskLabel=(task:Data)=>task.status==='cancelled'?'已取消':task.feedback_status==='sent'?'已反馈':task.status==='completed'?'已核实，待反馈':task.status==='in_progress'?'核实中':task.status==='blocked'?'等待前置事项':'待核实';
const localDate=(iso:string)=>new Date(new Date(iso).getTime()+8*3600000).toISOString().slice(0,16);
const needText=(value:unknown)=>String(value||'').replace(/\b(?:usage_tasks|required_software|purchase_budget|customer_identity|purchase_concerns|agreed_followup|purchase_intent)\s*[:：]\s*/g,'');
type Props={open:boolean;onClose:()=>void;conversationId:string;customerName:string;state:Data;focusedTaskId?:string;editable:boolean;updating:boolean;analysisFailed:boolean;currentReply:boolean;onChanged:()=>unknown;onJob:(id:string)=>void;onRetry:()=>void;onAdopt:(text:string,id:string)=>void};

export function VerificationDesk(p:Props){
 const tasks:Data[]=(p.state.tasks||[]).filter((t:Data)=>t.kind==='verify');
 const [selected,setSelected]=useState(p.focusedTaskId||tasks.find(needsVerificationFeedback)?.id||tasks[0]?.id||'');
 const task=tasks.find(t=>t.id===selected)||tasks.find(needsVerificationFeedback)||tasks[0];
 return <Modal title="门店核实" centered open={p.open} onCancel={p.onClose} footer={null} width={940} className="verification-modal">
  <p className="verification-customer">{p.customerName} · 会话 {p.conversationId.slice(-6)}</p>
  {tasks.length>1&&<div className="verification-task-picker" aria-label="选择核实事项">{tasks.map(t=><button key={t.id} aria-pressed={task?.id===t.id} onClick={()=>setSelected(t.id)}>{t.title}<small>{taskLabel(t)}</small></button>)}</div>}
  {task?<VerificationWork key={task.id} {...p} task={task}/>:<p>当前没有核实事项。</p>}
 </Modal>;
}

function VerificationWork({task,...p}:Props&{task:Data}){
 const stored=task.verification||{};
 const [kind,setKind]=useState(stored.kind||(/售价|价格|报价|库存|配置.*预算/.test(task.title)?'price':'compatibility'));
 const [conclusion,setConclusion]=useState(stored.conclusion||''),[summary,setSummary]=useState(stored.summary||''),[conditions,setConditions]=useState(stored.conditions||''),[source,setSource]=useState(stored.source||'');
 const [configuration,setConfiguration]=useState(stored.configuration||''),[price,setPrice]=useState(stored.price_text||''),[validUntil,setValidUntil]=useState(stored.valid_until?localDate(stored.valid_until):'');
 const [due,setDue]=useState(localDate(new Date(Date.now()+4*3600000).toISOString())),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[cancel,setCancel]=useState(false),[reason,setReason]=useState('');
 const completed=task.status==='completed',unconfirmed=conclusion==='unconfirmed';
 const disabled=!p.editable||busy||task.status==='blocked'||p.updating;
 const valid=conclusion&&summary.trim()&&(unconfirmed?due&&new Date(due+'+08:00').getTime()>Date.now():source.trim()&&(conclusion!=='conditional'||conditions.trim())&&(kind!=='price'||configuration.trim()&&price.trim()&&validUntil&&new Date(validUntil+'+08:00').getTime()>Date.now()));
 const candidates:Data[]=p.currentReply&&!p.updating&&!['review','wait','pause'].includes(p.state.action?.kind)?(p.state.action?.candidates||[]).filter((c:Data)=>c.verification_ids?.includes(task.id)||c.price_feedback?.[task.id]?.length):[];
 async function update(body:Data){
  setBusy(true);setError('');setNotice('');
  try{const r=await api(`/conversations/${p.conversationId}/service-tasks/${task.id}`,'POST',{revision:p.state.revision,...body});
   window.dispatchEvent(new Event('followups-changed'));await p.onChanged();
   if(r.job_id){setNotice('核实结果已保存，正在生成客户回复…');p.onJob(r.job_id);}else setNotice(body.status==='waiting_staff'?'已保留待办，将按下次处理时间提醒。':'事项已更新。');
  }catch(e){setError(e instanceof Error?e.message:'保存失败，请重试');}finally{setBusy(false);}
 }
 function save(){
  const verification:Data={kind,conclusion,summary:summary.trim(),conditions:conditions.trim(),source:source.trim()};
  if(kind==='price'&&!unconfirmed)Object.assign(verification,{configuration:configuration.trim(),price_text:price.trim(),valid_until:new Date(validUntil+'+08:00').toISOString()});
  void update({status:unconfirmed?'waiting_staff':'completed',verification,...(unconfirmed?{due_at:new Date(due+'+08:00').toISOString()}:{})});
 }
 const step=task.feedback_status==='sent'?3:completed?2:task.status==='in_progress'?1:0;
 return <div className="verification-work">
  <div className="verification-title"><h3>{task.title}</h3><Tag color={step===3?'green':completed?'gold':'default'}>{taskLabel(task)}</Tag></div>
  <ol className="verification-steps">{['待核实','核实中','已核实 · 待反馈','已反馈'].map((label,i)=><li key={label} aria-current={i===step?'step':undefined} className={i<=step?'is-reached':''}>{label}</li>)}</ol>
  <div className="verification-context"><small>客户原问题</small><p>{task.evidence?.quote||task.title}</p>
   {['budget','software','tasks'].filter(k=>['known','partial'].includes(p.state.needs?.[k]?.status)&&p.state.needs[k].value).map(k=><p key={k}><b>{{budget:'预算',software:'应用',tasks:'用途'}[k]}：</b>{needText(p.state.needs[k].value)}</p>)}
   {!completed&&<p className="verification-hint">{kind==='price'?'核对具体在售配置、门店价格和有效期；正式报价仍使用已授权的价格规则。':'优先查对应产品资料；资料未说明的适配结论，请通过门店实测或明确记录核实，并保留系统、软件版本和负载限制。'} 核实等待期间可继续处理其他需求。</p>}
  </div>
  {error&&<Alert type="error" message={error}/>} {notice&&!completed&&<Alert type="info" role="status" message={notice}/>}
  {completed?<>
   <div className="verification-result"><small>已登记结果</small><p>{task.result}</p></div>
   {task.feedback_status==='sent'?<Alert type="success" message={'已反馈客户 · '+time(task.feedback_at)} description="核实已闭环，可继续处理本轮需求或报价。"/>:<div className="verification-feedback">
    <h4>反馈客户</h4>
    {p.updating?<Alert type="info" role="status" message="正在根据核实结果生成客户回复…"/>:candidates.length?<><ChatMessageContent text={candidateReply(p.state,candidates[0])}/><p className="verification-hint">采用后填入会话输入框，发送成功才记为已反馈。</p><Button type="primary" disabled={!p.editable} onClick={()=>{p.onAdopt(candidateReply(p.state,candidates[0]),candidates[0].id);p.onClose();}}>采用回复并返回会话</Button></>:<Alert type={p.analysisFailed?'warning':'info'} message={p.analysisFailed?'客户回复生成未完成，核实结果已保存。':'结果已登记，等待准备客户回复。'} action={<Button disabled={!p.editable} onClick={p.onRetry}>{p.analysisFailed?'重试生成回复':'生成客户回复'}</Button>}/>}
   </div>}
  </>:task.status==='cancelled'?<p>该事项已取消：{task.result}</p>:<>
   <div className="verification-form">
    <label>核实类型<select aria-label="核实类型" value={kind} disabled={disabled} onChange={e=>setKind(e.target.value)}><option value="compatibility">软件适配与使用表现</option><option value="price">价格与在售配置</option><option value="other">其他产品问题</option></select></label>
    <label>核实结论<select aria-label="核实结论" value={conclusion} disabled={disabled} onChange={e=>setConclusion(e.target.value)}><option value="" disabled>请选择核实结论</option><option value="confirmed">已确认</option><option value="supported">可用</option><option value="unsupported">不适用</option><option value="conditional">有条件可用</option><option value="unconfirmed">暂未确认，继续核实</option></select></label>
    <label className="wide">结论说明<Input.TextArea aria-label="结论说明" value={summary} disabled={disabled} onChange={e=>setSummary(e.target.value)} maxLength={500} autoSize={{minRows:2,maxRows:4}} placeholder={unconfirmed?'说明暂未确认的原因和下一步怎么查':'填写确实核实到的结论，保留型号和版本'}/></label>
    <label className="wide">适用条件与限制<Input.TextArea aria-label="适用条件与限制" value={conditions} disabled={disabled} onChange={e=>setConditions(e.target.value)} maxLength={500} autoSize={{minRows:2,maxRows:4}} placeholder="例如操作系统、应用版本、测试场景，以及未覆盖的情况"/></label>
    <label className="wide">核实依据<Input aria-label="核实依据" value={source} disabled={disabled} onChange={e=>setSource(e.target.value)} maxLength={500} placeholder="产品资料链接、门店测试记录编号或负责人确认记录"/></label>
    {kind==='price'&&!unconfirmed&&<><label className="wide">具体型号与配置<Input aria-label="具体型号与配置" value={configuration} disabled={disabled} onChange={e=>setConfiguration(e.target.value)} maxLength={200}/></label><label>核实价格<Input aria-label="核实价格" value={price} disabled={disabled} onChange={e=>setPrice(e.target.value)} maxLength={100}/></label><label>价格有效期（北京时间）<input aria-label="价格有效期（北京时间）" type="datetime-local" value={validUntil} disabled={disabled} onChange={e=>setValidUntil(e.target.value)}/></label></>}
    {unconfirmed&&<label className="wide">下次处理时间（北京时间）<input aria-label="下次处理时间（北京时间）" type="datetime-local" value={due} disabled={disabled} onChange={e=>setDue(e.target.value)}/></label>}
   </div>
   {task.last_attempt&&<p className="verification-hint">上次核查：{task.last_attempt.summary}</p>}
   <div className="verification-actions">{task.status==='waiting_staff'&&<Button disabled={disabled} onClick={()=>void update({status:'in_progress'})}>开始核实</Button>}<Button type="primary" disabled={disabled||!valid} loading={busy} onClick={save}>{unconfirmed?'保留待办并安排下次核实':'保存并生成客户回复'}</Button><Button type="text" disabled={disabled} onClick={()=>setCancel(!cancel)}>取消事项</Button></div>
   {cancel&&<div className="verification-cancel"><label>取消原因<Input aria-label="取消原因" value={reason} maxLength={1000} onChange={e=>setReason(e.target.value)}/></label><Button disabled={disabled||!reason.trim()} onClick={()=>void update({status:'cancelled',result:reason.trim()})}>确认取消事项</Button></div>}
  </>}
 </div>;
}
