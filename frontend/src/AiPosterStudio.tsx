import React,{useEffect,useRef,useState} from 'react';
import {Alert,Button,Input,Select,Tag} from 'antd';
import {DownloadOutlined,PictureOutlined,ThunderboltOutlined} from '@ant-design/icons';
import {api,ApiError,Data,requestId,statuses,time} from './api';
import {useData} from './lifecycle';

type Props={work:Data;imageId:string;dirty:boolean;busy?:boolean};

export function AiPosterStudio({work,imageId,dirty,busy=false}:Props){
 const [scene,setScene]=useState(work.brief.scene||''),[ratio,setRatio]=useState('3:4');
 const [submitting,setSubmitting]=useState(false),[uncertain,setUncertain]=useState(false),[error,setError]=useState(''),[submitted,setSubmitted]=useState<Data|null>(null);
 const attempt=useRef<Data|null>(null),inFlight=useRef(false);
 const jobs=useData('/jobs',3000),assets=useData('/assets',10000);
 const job=submitted?(jobs.data?.find((item:Data)=>item.id===submitted.id)||submitted):jobs.data?.find((item:Data)=>item.kind==='poster'&&item.target_id===work.id);
 const active=job&&['queued','running','waiting_remote'].includes(job.status);
 const approved=['passed','manual_passed'].includes(work.report.status)&&!work.report.blocked;
 const saved=(assets.data||[]).filter((item:Data)=>item.kind==='ai_poster'&&item.metadata_json.work_id===work.id);
 const poster=saved.find((item:Data)=>item.id===job?.result?.asset_id)||saved[0];
 const review=poster?.metadata_json.review;
 useEffect(()=>{if(job?.status==='completed')void assets.refresh();},[job?.id,job?.status]);
 const generate=async()=>{
  if(inFlight.current||active)return;
  inFlight.current=true;setSubmitting(true);setError('');
  attempt.current??={image_id:imageId,expected_version:work.version,scene,ratio,request_id:requestId()};
  try{
   const result=await api('/works/'+work.id+'/poster-tasks','POST',attempt.current);
   setSubmitted({id:result.job_id,kind:'poster',target_id:work.id,status:'queued'});attempt.current=null;setUncertain(false);
   await jobs.refresh();
  }catch(reason){
   const rejected=reason instanceof ApiError&&reason.status>=400&&reason.status<500;
   if(rejected)attempt.current=null;else setUncertain(true);
   setError((reason as Error).message+(rejected?'':'；再次点击会确认同一次提交，不会创建第二个生成任务。'));
  }
  finally{inFlight.current=false;setSubmitting(false);}
 };
 const control=async(action:'retry'|'cancel')=>{
  if(!job)return;
  setError('');
  try{await api('/jobs/'+job.id+'/'+action,'POST');await jobs.refresh();}
  catch(reason){setError((reason as Error).message);}
 };
 return <section className="panel image-studio">
  <div className="ai-poster-controls">
  <h3><PictureOutlined/> AI海报设计</h3>
  <p className="muted">AI规划设计方案，生成整张海报，再对照产品原图检查画面与文字。</p>
  <label htmlFor="ai-poster-ratio">画布比例</label>
  <Select id="ai-poster-ratio" aria-label="海报画布比例" value={ratio} disabled={!!active||submitting||uncertain} onChange={setRatio} options={['1:1','3:4','16:9'].map(value=>({value,label:value}))}/>
  <label htmlFor="ai-poster-scene">使用场景与创意要求</label>
  <Input.TextArea id="ai-poster-scene" rows={4} maxLength={800} value={scene} disabled={!!active||submitting||uncertain} onChange={event=>setScene(event.target.value)} placeholder="例如：大学学习、写代码，阳光下的校园书桌，年轻清爽"/>
  {imageId&&<details><summary>核对产品参考图</summary><img className="background-thumb" src={'/api/knowledge/images/'+imageId} alt="海报产品参考原图"/></details>}
  {!approved&&<Alert type="info" message="请先通过内容检查或人工确认，再生成海报。"/>}
  {dirty&&<Alert type="info" message="请先保存作品修改。"/>}
  <Button aria-label="AI设计整张海报" type="primary" block icon={<ThunderboltOutlined/>} loading={submitting||job?.status==='running'} disabled={!imageId||dirty||busy||!approved||scene.trim().length<2||!!active||submitting||!jobs.data||!!jobs.error} onClick={()=>void generate()}>AI设计整张海报</Button>
  <small>通常生成1张；需要自动调整时最多生图2次，使用当前图片服务额度。</small>
  {error&&<Alert type="error" showIcon message={error}/>}
  {jobs.error&&<Alert type="error" message="暂时无法读取海报任务，请刷新后再生成。"/>}
  {job&&<div className="task-progress"><Tag>{statuses[job.status]||job.status}</Tag><p>{job.step||'正在准备海报任务'}</p>{job.error&&<Alert type="warning" message={job.error}/>}
   {['waiting_remote','failed','cancelled'].includes(job.status)&&job.remote_id&&<Button size="small" onClick={()=>void control('retry')}>继续查看原任务</Button>}
   {['queued','running','waiting_remote'].includes(job.status)&&<Button size="small" onClick={()=>void control('cancel')}>停止等待</Button>}
  </div>}
  </div>
  <div className="ai-poster-output">
  {!poster&&<div className="ai-poster-placeholder">{imageId&&<img src={'/api/knowledge/images/'+imageId} alt="待设计的产品参考图"/>}<p>生成后，在这里预览完整海报</p></div>}
  {poster&&<>
   <img className="poster-preview" src={'/api/assets/'+poster.id} alt="AI设计的产品海报"/>
   <a href={'/api/assets/'+poster.id} download="知客-AI海报.png"><Button block icon={<DownloadOutlined/>}>下载AI海报</Button></a>
   {review&&<Alert showIcon type={review.review_state==='completed'&&review.verdict==='pass'?'success':'warning'} message={review.review_state!=='completed'?'视觉检查未完成，请人工核对':review.verdict==='pass'?'AI视觉检查通过':'AI检查后仍需调整'} description={review.summary}/>}
   {poster.metadata_json.design_engine&&<details><summary>设计方案与检查意见 · {poster.metadata_json.design_engine}</summary>
    <p className="muted">{poster.metadata_json.design_spec?.composition_notes}</p>
    {review?.issues?.map((issue:Data,index:number)=><p key={index}>{issue.description}</p>)}
    <small>AI检查用于辅助筛查，产品外观与重要文案仍需人工确认。</small>
   </details>}
   <small>AI创意效果，请对照参考原图核对产品外观和文字。作品第 {poster.metadata_json.work_version} 版。</small>
  </>}
  {saved.length>1&&<details><summary>已保存的AI海报 · {saved.length} 张</summary>{saved.map((item:Data)=><a style={{display:'block'}} key={item.id} href={'/api/assets/'+item.id} download="知客-AI海报.png">{time(item.created_at)} · {item.metadata_json.ratio} · 第{item.metadata_json.work_version}版</a>)}</details>}
  </div>
 </section>;
}
