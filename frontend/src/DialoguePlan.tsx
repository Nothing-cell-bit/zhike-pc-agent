import React,{useState} from 'react';
import {Alert,Button,Modal,Tag} from 'antd';
import {Data} from './api';
import {QualificationCheck} from './QualificationCheck';
import {ChatMessageContent} from './ChatMessageContent';
const labels:Record<string,string>={ask:'补充关键信息',recommend:'推荐回复',compare:'推荐回复',quote:'报价回复',inform:'推荐回复',wait:'等待客户回复',pause:'接待已暂停',review:'建议待重新整理'};
type Props={state:Data;editable:boolean;updating:boolean;failed?:boolean;analysisError?:string;onAdopt:(text:string,actionId:string)=>void;conversationId?:string;canVerify?:boolean;onChanged?:()=>void;onQualificationChanged?:()=>void;onRegenerate?:()=>void;regenerating?:boolean;regenerateError?:string};
function quoteContext(state:Data){
 const action=state.action||{};
 const ids=new Set(action.option_ids?.length?action.option_ids:state.selection?.status==='confirmed'?[state.selection.option_id]:(state.quotes||[]).filter((q:Data)=>q.state!=='invalidated').map((q:Data)=>q.option_id));
 return {options:state.goal==='information'?[]:(state.options||[]).filter((o:Data)=>ids.has(o.id)),formalQuote:state.goal==='quote'&&action.kind==='quote'&&(state.quotes||[]).some((q:Data)=>q.state==='ready_for_review'&&ids.has(q.option_id))};
}
export function candidateReply(state:Data,candidate:Data):string{return quoteContext(state).formalQuote?(candidate.intro||candidate.reply||''):(candidate.reply||candidate.intro||candidate.answer||'');}
export function DialoguePlan({state,editable,updating,failed=false,analysisError='',onAdopt,onRegenerate,regenerating=false,regenerateError=''}:Props){
 const [moreOpen,setMoreOpen]=useState(false),[selectedId,setSelectedId]=useState('');
 const action=state.action||{};const {formalQuote}=quoteContext(state);
 const body=(candidate:Data):string=>candidateReply(state,candidate);
 const candidates:Data[]=(action.candidates||[]).filter((candidate:Data)=>body(candidate).trim());
 const selected=candidates.find(candidate=>candidate.id===selectedId)||candidates[0];
 const staffWaiting=action.kind==='wait'&&state.next_owner==='staff';
 const busy=updating||regenerating;
 const adopt=(candidate:Data)=>{setSelectedId(candidate.id);onAdopt(body(candidate),candidate.id);setMoreOpen(false);};
 return <section className="dialogue-plan" aria-label="接待建议">
  {failed&&<Alert type="warning" message={analysisError?analysisError+'。已保留上次记录。':state.reply_generation_failed?'客户需求已更新，回复建议暂未生成。请点击“更新分析”重试。':'更新未完成，已保留上次记录。请点击“更新分析”重试。'}/>}
  {!moreOpen&&regenerateError&&<Alert type="warning" message={regenerateError}/>}
  {updating?<div className="assistant-reply-empty" role="status">正在整理推荐回复…</div>:selected?
   <article className="assistant-reply-preview">
    <div className="assistant-reply-heading"><h3>{labels[action.kind]||'推荐回复'}</h3>{candidates.length>1&&<Button type="text" size="small" onClick={()=>setMoreOpen(true)}>更多</Button>}</div>
    {selected.label&&<span className="assistant-reply-label">{selected.label}</span>}
    <div className="dialogue-reply"><ChatMessageContent text={body(selected)}/></div>
    <Button type="primary" block disabled={!editable||busy} onClick={()=>adopt(selected)}>采用这条回复</Button>
    {formalQuote&&<p className="assistant-reply-note">发送时附上已核价的报价卡，详情见“会话详情”。</p>}
   </article>:
   <div className="assistant-reply-empty"><h3>{staffWaiting?'等待门店处理':labels[action.kind]||'回复建议'}</h3>
    {action.reply?<><div className="dialogue-reply"><ChatMessageContent text={formalQuote?(action.intro||action.reply):action.reply}/></div><Button type="primary" block disabled={!editable||busy||failed} onClick={()=>onAdopt(formalQuote?(action.intro||action.reply):action.reply,action.id)}>采用到输入框</Button></>:
     <p>{state.waiting_reason||(action.kind==='wait'?(staffWaiting?'请处理会话中的待核实或待办事项。':'上一条回复已发送，等待客户继续。'):'暂无可用推荐，可点击“更新分析”。')}</p>}
   </div>}
  {state.conflicts?.length>0&&<Alert type="warning" message="客户新表述与已锁定信息有差异，请在会话详情中核对。"/>}
  <Modal title="AI 推荐回复" centered open={moreOpen} onCancel={()=>setMoreOpen(false)} footer={null} width={960} destroyOnHidden className="reply-options-modal">
   <div className="reply-options-toolbar"><span>共 {candidates.length} 条可用回复，采用后填入输入框</span><Button loading={regenerating} disabled={!editable||updating} onClick={onRegenerate}>换一组回复</Button></div>
   {regenerateError&&<Alert type="warning" message={regenerateError}/>}
   {updating&&<Alert type="info" message="正在根据最新对话更新推荐，请稍候。"/>}
   <div className="reply-options-grid">{candidates.map((candidate,index)=><article className={'reply-choice reply-option'+(candidate.id===selected?.id?' is-selected':'')} key={candidate.id}>
    <div className="reply-option-heading"><span>推荐 {index+1}</span>{candidate.id===selected?.id&&<Tag>当前展示</Tag>}</div>
    <b>{candidate.label}</b><div className="dialogue-reply"><ChatMessageContent text={body(candidate)}/></div>
    <Button type="primary" block disabled={!editable||busy} onClick={()=>adopt(candidate)}>采用这条回复</Button>
   </article>)}</div>
  </Modal>
 </section>;
}

export function DialoguePricing({state,editable,updating,conversationId,canVerify,onChanged,onQualificationChanged}:Props){
 const {options}=quoteContext(state);
 return <section className="dialogue-pricing" aria-label="当前核价方案">
  {options.map((option:Data,index:number)=>{const quotes=(state.quotes||[]).filter((q:Data)=>q.option_id===option.id);return <div className="dialogue-option" key={option.id}><b>{state.selection?.status==='confirmed'&&state.selection.option_id===option.id?'已选配置':'方案'+(index+1)} · {option.name}</b><p>{quotes.some((q:Data)=>q.state==='ready_for_review'&&q.sku_ref)?option.variant.replace('（销售组合待核实）',''):option.variant}</p><Tag>{state.selection?.status==='confirmed'&&state.selection.option_id===option.id?state.selection.needs_revalidation?'待重新核对':state.selection.scope==='preference'?'已确认配置偏好':'客户已确认':'待客户确认'}</Tag>{quotes.map((quote:Data,i:number)=><div key={quote.id||i}>{quotes.length>1&&<small>{{L1:'单机标准',L2:'资格优惠',L3:'套装方案',L4:'审批专项'}[quote.level as 'L1'|'L2'|'L3'|'L4']}</small>}<p className="quote-amount">{quote.state==='invalidated'?'条件已变化，需重新核价':quote.total_minor!==null&&quote.total_minor!==undefined?(quote.delivery_status==='sent'?'已发送报价 ¥':'待客服复核 ¥')+(quote.total_minor/100).toLocaleString('zh-CN'):quote.state==='needs_configuration'?'销售组合待核实':quote.state==='needs_approval'?'等待报价审批':quote.state==='needs_qualification'?'优惠资格待核验':'门店价待核验'}</p></div>)}</div>;})}
  {state.goal==='quote'&&canVerify&&conversationId&&<QualificationCheck conversationId={conversationId} disabled={!editable||updating} codes={[...new Set<string>((state.quotes||[]).filter((q:Data)=>q.state==='needs_qualification').flatMap((q:Data)=>q.required_qualifications||[]))]} onSaved={()=>onQualificationChanged?onQualificationChanged():onChanged?.()}/>}
 </section>;
}
