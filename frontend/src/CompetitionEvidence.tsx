import React from 'react';
import ReactMarkdown from 'react-markdown';
import {Data} from './api';

const labels:Record<string,string>={audience:'目标人群',scene:'使用场景',buying_stage:'购买阶段',user_problem:'用户问题',goal:'内容目标',platform:'发布平台'};
const safeUrl=(url:string)=>/^https?:\/\//i.test(url||'')?url:undefined;

export function CompetitionEvidence({work}:{work:Data}){
 const c=work.content||{},r=work.report||{},brief=work.brief||{};
 const isIma=c.source_type==='ima';
 const scenario={...c.scenario,...Object.fromEntries(Object.keys(labels).filter(k=>brief[k]).map(k=>[k,brief[k]]))};
 const claims=r.claims||c.claims||[];
 const pending=Array.from(new Set<string>([...(c.pending||[]),...(r.pending||[])]));
 return <div className="competition-evidence">
  <SourceNotice content={c}/>
  <h3>一、场景判断</h3>
  <dl>{Object.entries(labels).map(([key,label])=><React.Fragment key={key}><dt>{label}</dt><dd>{scenario[key]||'待确认'}</dd></React.Fragment>)}</dl>
  {c.strategy&&<><h4>内容策略{c.strategy_current===false?'（修改前的策略，仅供追溯）':''}</h4><p style={{whiteSpace:'pre-wrap'}}>{c.strategy}</p></>}
  <h3>二、知识库依据</h3><p>产品型号：{c.product_name||'待确认'}</p>
  {(c.sources||[]).map((s:Data)=><div key={s.id}><b>{s.title}</b><p>资料编号：{s.id} · 版本：{s.version||'待确认'}</p>{(s.urls||[]).filter(safeUrl).map((u:string)=><p key={u}><a href={u} target="_blank" rel="noreferrer">{u}</a></p>)}</div>)}
  {claims.length?<ul>{claims.map((x:Data,i:number)=><li key={i}>{x.text}；依据：{x.source_id}</li>)}</ul>:<p>尚无当前版本的事实点，待核验。</p>}
  <h3>三、图文软文</h3><p>{c.title}</p><p>正文见图文预览。以下为配图依据：</p>
  {(c.images||[]).map((im:Data)=><div key={im.id}><b>{im.name}</b><p>{im.position||'位置待确认'} · {im.caption||im.description}</p><p>选图理由：{im.selection_reason||'历史稿件未记录'}</p><a href={safeUrl(im.source||im.url)} target="_blank" rel="noreferrer">{im.source||im.url||'图源待确认'}</a></div>)}
  <h3>四、核验结果</h3><p>状态：{r.blocked?'资料冲突，停止导出':r.status==='manual_passed'?'人工已通过':r.status==='passed'?'资料检查通过':'待检查或需调整'}；{c.source_type==='sample'?'公开副本未附原图及资料快照，不作为当前图源核验':isIma?(r.ima_verified?'ima 来源快照完整性已验证':'ima 来源已保存，等待本版本核验'):'本地图源，不作为 ima 图源证明'}。</p>
  <p>产品事实：{claims.length} 项；图片型号与合规：{r.status==='manual_passed'?'已人工确认，原始检查记录保留如下':r.status==='passed'?'本次检查通过，仍需发布前复核':'待核验或修订'}。</p>
  {r.approval&&<p>人工确认：{r.approval.display_name}；{r.approval.approved_at}；确认说明：{r.approval.note}</p>}
  <ul>{(r.issues||[]).map((x:Data,i:number)=><li key={i}>{x.type}：{x.text}</li>)}</ul>
  <p>待确认信息：{pending.length?pending.join('；'):'本次记录未列出'}</p>
  <p>模型：{r.model||'未记录'}；提示词：{r.prompt_version||c.prompt_version||'历史稿件未记录'}</p>
 </div>;
}

export function SourceNotice({content}:{content:Data}){
 if(content.source_type==='sample')return <p className="muted">公开历史样例：保留真实最终文案，已省略原图与资料快照；仅供阅读和草稿导出，不作为当前 ima 核验结果。</p>;
 return <p className="muted">{content.source_type==='ima'?'知识来源：ima · '+(content.knowledge_base_name||'指定比赛知识库'):'知识来源：本地 ZIP'}{content.fallback_reason?'；ima 调用失败，已回退本地：'+content.fallback_reason:''}</p>;
}

export function ArticleBody({content}:{content:Data}){
 const blocks=(content.body||'').trim().split(/\n\s*\n/).filter((s:string)=>s.trim());
 const images=content.images||[];
 return <>{Array.from({length:blocks.length+1},(_,slot)=><React.Fragment key={slot}>
  {slot>0&&<ArticleMarkdown text={blocks[slot-1]}/>}
  {images.filter((im:Data,i:number)=>{
   const legacy=/第(\d+)[段块]/.exec(im.position||'');
   const after=Number.isInteger(im.after_block)?im.after_block:legacy?Number(legacy[1]):i+1;
   return Math.max(0,Math.min(after,blocks.length))===slot;
  }).map((im:Data)=><figure key={im.id}><img src={'/api/knowledge/images/'+im.id} alt={im.caption||im.description||im.name}/><figcaption>{im.caption||im.description}</figcaption></figure>)}
 </React.Fragment>)}</>;
}

// Keep Markdown rendering identical to the editor while respecting recorded image slots.
function ArticleMarkdown({text}:{text:string}){return <div className="prose"><ReactMarkdown components={{img:()=>null}}>{text}</ReactMarkdown></div>;}

export function TaskQuestions({result}:{result?:Data}){
 const questions=[...(result?.needs_confirmation||[]),...(result?.questions||[])];
 return questions.length?<div role="status"><ul>{questions.map((q:string,i:number)=><li key={i}>{q}</li>)}</ul></div>:null;
}
