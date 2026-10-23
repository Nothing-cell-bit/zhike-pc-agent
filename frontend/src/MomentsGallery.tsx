import React,{useEffect,useRef,useState} from 'react';
import {Alert,Button,Image,Input,Select,Tag} from 'antd';
import {ArrowLeftOutlined,ArrowRightOutlined,DownloadOutlined,PictureOutlined,ThunderboltOutlined} from '@ant-design/icons';
import {api,ApiError,Data,requestId,statuses} from './api';
import {useData} from './lifecycle';
import './momentsGallery.css';
import {workImageUrl} from './workImages';

export const GALLERY_COUNTS=[{value:0,label:'纯文字'},{value:1,label:'单图'},{value:3,label:'三图'},{value:6,label:'六图'},{value:9,label:'九宫格'}];
export const GALLERY_MODES=[{value:'mixed',label:'产品原图＋AI场景图'},{value:'original',label:'只用产品原图'},{value:'ai',label:'全部AI场景图'}];
export function galleryCounts(count:number,mode:string,available=99){const original=mode==='original'?count:mode==='mixed'?Math.min(Math.floor(count/3),3,available):0;return {original,ai:count-original};}

export function MomentsGalleryGrid({items,onMove}:{items:Data[];onMove?:(from:number,to:number)=>void}){
 return <Image.PreviewGroup><div className="moments-picture-grid" data-count={items.length} aria-label={`${items.length}张朋友圈配图`}>{items.map((item,index)=><div className="moments-picture" key={item.image_id||item.asset_id||item.url}>
  <Image src={item.url} alt={item.title||'朋友圈配图'+(index+1)} preview={{mask:'查看原图'}}/>
  {onMove&&<div className="moments-picture-order"><span>{index+1} · {item.kind==='ai'?'AI场景':'产品原图'}</span><div><a href={item.url} download={item.filename||'moments-picture.png'} aria-label={`下载第${index+1}张配图`}><DownloadOutlined/></a><Button type="text" size="small" aria-label={`第${index+1}张向前移动`} disabled={index===0} icon={<ArrowLeftOutlined/>} onClick={()=>onMove(index,index-1)}/><Button type="text" size="small" aria-label={`第${index+1}张向后移动`} disabled={index===items.length-1} icon={<ArrowRightOutlined/>} onClick={()=>onMove(index,index+1)}/></div></div>}
 </div>)}</div></Image.PreviewGroup>;
}

export function selectedMomentsGallery(work:Data,data?:Data){
 return [data?.gallery,data?.previous_gallery].find(album=>album&&album.work_version<=work.version&&
  (!album.work_id||album.work_id===work.id)&&(!album.product_id||album.product_id===work.brief.product_id));
}
const publicationDownload=(work:Data)=>`/api/works/${work.id}/export?format=zip&scope=publication&draft=${!['passed','manual_passed'].includes(work.report.status)}`;

export function MomentsGalleryFeed({work,content,fallback}:{work:Data;content:Data;fallback?:React.ReactNode}){
 const result=useData('/works/'+work.id+'/moments-gallery',5000),gallery=selectedMomentsGallery(work,result.data);
 return <>{gallery?<MomentsGalleryGrid items={gallery.items}/>:fallback}{result.error&&<Alert type="error" message="朋友圈配图加载失败" action={<Button size="small" onClick={()=>void result.refresh()}>重试</Button>}/>}</>;
}

export function MomentsGalleryEditor({work,images,dirty,onManage}:{work:Data;images:Data[];dirty:boolean;onManage:()=>void}){
 const result=useData('/works/'+work.id+'/moments-gallery',5000);
 const album=selectedMomentsGallery(work,result.data);
 const stale=album&&album.work_version!==work.version;
 const items=album?.items||images.map(image=>({image_id:image.id,kind:image.source_type==='user_upload'?'upload':'original',url:workImageUrl(image.id),title:image.caption||image.description||image.name}));
 return <section className="moments-editor-pictures" aria-label="朋友圈配图编辑区">
  <div className="moments-editor-pictures-heading"><h3>朋友圈配图{items.length?` · ${items.length}张`:''}</h3><Button aria-label="管理朋友圈配图" icon={<PictureOutlined/>} onClick={onManage}>管理配图</Button></div>
  {result.error&&<Alert type="error" message="配图暂时加载失败" action={<Button size="small" onClick={()=>void result.refresh()}>重试</Button>}/>}
  {!!items.length&&<MomentsGalleryGrid items={items}/>}
  {!items.length&&<p className="muted">{result.data?'还没有朋友圈配图。可通过工具栏上传本地图片，或在“管理配图”中准备单图、三图、六图或九宫格。':'正在读取朋友圈配图…'}</p>}
  {stale&&<p className="muted">沿用第{album.work_version}版的配图，预览和导出搭配当前文案，无需重新生成。</p>}
  {dirty&&!!items.length?<p className="muted">配图已保留，当前文案还有未保存的修改。</p>:album&&<a className="moments-editor-download" href={publicationDownload(work)} download>下载整组配图与当前文案</a>}
 </section>;
}

export function MomentsGalleryStudio({work,dirty,busy=false}:{work:Data;dirty:boolean;busy?:boolean}){
 const [count,setCount]=useState<number>(work.brief.moments_image_count||9),[mode,setMode]=useState(work.brief.moments_image_mode||'mixed'),[scene,setScene]=useState(work.brief.scene||'');
 const [submitting,setSubmitting]=useState(false),[error,setError]=useState(''),[uncertain,setUncertain]=useState(false),[submitted,setSubmitted]=useState('');
 const attempt=useRef<Data|null>(null),inFlight=useRef(false),jobs=useData('/jobs',3000),albums=useData('/works/'+work.id+'/moments-gallery',5000);
 const job=jobs.data?.find((item:Data)=>submitted?item.id===submitted:item.kind==='moments_gallery'&&item.target_id===work.id);
 const active=job&&['queued','running','waiting_remote'].includes(job.status),album=selectedMomentsGallery(work,albums.data);
 const stale=album&&album.work_version!==work.version;
 const approved=['passed','manual_passed'].includes(work.report.status)&&!work.report.blocked;
 const originalImages=work.available_images?.filter((image:Data)=>image.source_type!=='user_upload');
 const expected=galleryCounts(count,mode,originalImages?.length??99);
 const tooFew=mode==='original'&&count>(originalImages?.length??99);
 useEffect(()=>{if(job?.status==='completed')void albums.refresh();},[job?.id,job?.status]);
 const generate=async()=>{
  if(inFlight.current||active)return;inFlight.current=true;setSubmitting(true);setError('');
  attempt.current??={expected_version:work.version,count,mode,scene,request_id:requestId()};
  try{const response=await api('/works/'+work.id+'/moments-gallery-tasks','POST',attempt.current);setSubmitted(response.job_id);attempt.current=null;setUncertain(false);await jobs.refresh();}
  catch(reason){const rejected=reason instanceof ApiError&&reason.status>=400&&reason.status<500;if(rejected)attempt.current=null;else setUncertain(true);setError((reason as Error).message+(rejected?'':'；再次点击只确认本次请求，不会创建另一组付费任务。'));}
  finally{inFlight.current=false;setSubmitting(false);}
 };
 const control=async(action:'retry'|'cancel')=>{setError('');try{await api('/jobs/'+job.id+'/'+action,'POST');await jobs.refresh();}catch(reason){setError((reason as Error).message);}};
 const move=async(from:number,to:number)=>{
  if(!album||to<0||to>=album.items.length)return;const order=album.items.map((_:Data,index:number)=>index);[order[from],order[to]]=[order[to],order[from]];
  setError('');try{await api(`/works/${work.id}/moments-gallery/${album.id}`,'PATCH',{expected_version:work.version,expected_revision:album.revision,order});await albums.refresh();}catch(reason){setError((reason as Error).message);}
 };
 const partial=job?.payload?.items?.filter((item:Data)=>item.kind==='original'||item.asset_id).map((item:Data)=>({...item,url:item.kind==='original'?'/api/knowledge/images/'+encodeURIComponent(item.image_id):'/api/assets/'+encodeURIComponent(item.asset_id)}))||[];
 return <section className="moments-gallery-studio">
  <div className="moments-gallery-controls"><h3><PictureOutlined/> 朋友圈配图</h3><p className="muted">组合模式用原图展示真实产品，AI图只补充学习氛围，不重绘电脑。每张都是独立图片，可调整顺序后整组下载。</p>
   <label htmlFor="moments-count">配图数量</label><Select id="moments-count" aria-label="配图数量" value={count} disabled={!!active||submitting||uncertain} onChange={setCount} options={GALLERY_COUNTS.filter(choice=>choice.value>0)}/>
   <label htmlFor="moments-mode">图片来源</label><Select id="moments-mode" aria-label="图片来源" value={mode} disabled={!!active||submitting||uncertain} onChange={setMode} options={GALLERY_MODES}/>
   <label htmlFor="moments-scene">场景与风格要求</label><Input.TextArea id="moments-scene" aria-label="配图场景与风格" rows={4} maxLength={800} value={scene} disabled={!!active||submitting||uncertain} onChange={event=>setScene(event.target.value)} placeholder="例如：课堂、图书馆、宿舍写代码；自然暖白光、统一清爽色调，每张不同镜头"/>
   <p className="moments-generation-count">{expected.original}张产品原图 ＋ {expected.ai}张AI场景图{expected.ai>0&&<small>将提交 {expected.ai} 张图片生成，使用当前图片服务额度；不会自动重复生成失败图片。</small>}</p>
   {tooFew&&<Alert type="info" message={`当前只有${originalImages?.length||0}张同型号原图，请减少数量或切换组合模式。`}/>}
   {(!approved||dirty)&&<Alert type="info" message={dirty?'请先保存文案修改。':'请先完成文案检查或人工确认，再准备配图。'}/>}
   <Button aria-label={mode==='original'?'准备产品配图':`生成${count===9?'九宫格':count+'张'}配图`} type="primary" icon={<ThunderboltOutlined/>} loading={submitting||job?.status==='running'} disabled={dirty||busy||!approved||tooFew||scene.trim().length<2||!!active||submitting||!jobs.data||!!jobs.error} onClick={()=>void generate()}>{mode==='original'?'准备产品配图':`生成${count===9?'九宫格':count+'张'}配图`}</Button>
   {error&&<Alert type="error" showIcon message={error}/>}
   {job&&<div className="task-progress"><Tag>{statuses[job.status]||job.status}</Tag><p>{job.step}</p><small>已完成 {job.result?.completed_count||0}/{job.result?.total_count||job.payload?.count||count} 张</small>{job.error&&<Alert type="warning" message={job.error}/>}
    {['failed','waiting_remote','cancelled'].includes(job.status)&&<Button size="small" onClick={()=>void control('retry')}>继续查看原任务</Button>}
    {['queued','running','waiting_remote'].includes(job.status)&&<Button size="small" onClick={()=>void control('cancel')}>停止等待</Button>}
   </div>}
  </div>
  <div className="moments-gallery-output">
   {album?<><MomentsGalleryGrid items={album.items} onMove={!dirty&&!busy&&!stale?(from,to)=>void move(from,to):undefined}/><a href={publicationDownload(work)} download="朋友圈配图.zip"><Button icon={<DownloadOutlined/>}>下载整组配图与当前文案</Button></a><small>{album.original_count}张产品原图 · {album.ai_count}张AI场景图 · 作品第{album.work_version}版</small>{stale&&<Alert type="info" message="已有配图继续沿用，预览和导出使用当前文案，无需重新生成图片。"/>}{album.ai_count>0&&<Alert type="info" message="AI场景图为创意示意，请对照产品原图核对外观后使用。"/>}</>
    :partial.length?<><MomentsGalleryGrid items={partial}/><p className="muted">当前显示已完成的图片，完整相册生成后可调整顺序和下载。</p></>
    :<div className="moments-gallery-empty"><PictureOutlined/><p>生成后在这里预览整组图片</p><small>九宫格为九张独立图片，不会拼成一张大图。</small></div>}
  </div>
 </section>;
}
