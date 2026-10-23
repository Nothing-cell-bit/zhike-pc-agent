import {ChatMaterialPicker} from './ChatMaterialPicker';
import React,{useEffect,useMemo,useRef,useState} from 'react';
import {Alert,App,Button,Descriptions,Drawer,Dropdown,Empty,Form,Input,Modal,Select,Spin,Tag,Tabs} from 'antd';
import {ArrowLeftOutlined,CheckCircleOutlined,CopyOutlined,DownloadOutlined,EyeOutlined,MoreOutlined,PictureOutlined,SaveOutlined,SettingOutlined,ThunderboltOutlined} from '@ant-design/icons';
import {api,Data,statuses,time} from './api';
import {useData} from './lifecycle';
import {useWorkDraft} from './useWorkDraft';
import {registerEditorNavigation,requestEditorNavigation} from './editorNavigation';
import {RichBodyEditor,RichBodyHandle,RichTextField} from './RichBodyEditor';
import {ArticleBody,CompetitionEvidence} from './CompetitionEvidence';
import {ContentReview} from './ContentReview';
import {AiPosterStudio} from './AiPosterStudio';
import './writer.css';
import {PlatformArticlePreview as ArticlePreview,publicationCopy} from './PlatformArticlePreview';
import {PLATFORM_CHOICES} from './PlatformPicker';
import {MomentsGalleryStudio,MomentsGalleryEditor} from './MomentsGallery';
import {WorkImageLibrary} from './WorkImageLibrary';

type Context={id:string;onBack:()=>void;products:Data[];navigate:(view:string,id?:string)=>void;
 modal:ReturnType<typeof App.useApp>['modal'];action:(fn:()=>Promise<any>)=>Promise<any>;
 watch:(id:string,onDone?:(job:Data)=>void,onSettled?:(job:Data)=>void)=>void};

export default function WorkEditor(ctx:Context){
 const detail=useData('/works/'+ctx.id);
 return detail.data?<Writer key={ctx.id} ctx={ctx} initial={detail.data}/>:detail.error?<Alert type="error" message={detail.error}/>:<div className="loading"><Spin/> 正在打开文稿</div>;
}

function Writer({ctx,initial}:{ctx:Context;initial:Data}){
 const [reviewBusy,setReviewBusy]=useState(false),[reviewError,setReviewError]=useState('');
 const [panel,setPanel]=useState(''),[preview,setPreview]=useState(false),[imagesOpen,setImagesOpen]=useState(false);
 const [historyVersion,setHistoryVersion]=useState<Data|null>(null),[copied,setCopied]=useState(false);
 const [settingsForm]=Form.useForm();const bodyRef=useRef<RichBodyHandle|null>(null),bypass=useRef(false);
 const {work:w,draft,dirty,saving,error,change,save,accept}=useWorkDraft(initial,reviewBusy);
 const current=useRef({dirty,saving,save});current.current={dirty,saving,save};
 useEffect(()=>registerEditorNavigation(proceed=>{
  if(bypass.current){bypass.current=false;proceed();return;}
  if(!current.current.dirty&&!current.current.saving){proceed();return;}
  const confirmation=ctx.modal.confirm({title:'还有未保存的修改',content:'可以先保存再离开，或继续留在文稿中编辑。',okText:'保存并离开',cancelText:'继续编辑',
   onOk:async()=>{const result=await current.current.save();if(!result)throw new Error('尚未保存成功');proceed();},
   footer:(_,buttons)=><><Button type="text" danger onClick={()=>{confirmation.destroy();proceed();}}>不保存并离开</Button><buttons.CancelBtn/><buttons.OkBtn/></>});
 }),[ctx.modal]);
 useEffect(()=>{
  const keydown=(event:KeyboardEvent)=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();void current.current.save();}};
  window.addEventListener('keydown',keydown);return()=>window.removeEventListener('keydown',keydown);
 },[]);
 const status=dirty?'unchecked':w.report.status;
 const pending=Array.from(new Set<string>([...(draft.pending||[]),...(w.report.pending||[])]));
 const issues=w.report.issues||[],count=issues.length+pending.length;
 const canExport=['passed','manual_passed'].includes(status);
 const [uploads,setUploads]=useState<Data[]>([]),[pendingImages,setPendingImages]=useState<Data[]>([]);
 const choices=useMemo(()=>Array.from(new Map([...(w.available_images||[]),...uploads].map(image=>[image.id,image])).values()),[w.available_images,uploads]);
 const isMoments=w.brief.platform==='朋友圈';
 const posterImageId=[...draft.images,...choices].find(image=>!image.id.startsWith('upload-'))?.id||'';
 useEffect(()=>{
  if(!pendingImages.length||reviewBusy||!bodyRef.current)return;
  const image=pendingImages[0];
  if(draft.images.length<6&&!draft.images.some((item:Data)=>item.id===image.id))bodyRef.current.insertImage(image);
  setPendingImages(items=>items.slice(1));
 },[pendingImages,choices,reviewBusy,draft.images]);
 const runReview=async(kind:'verify'|'repair')=>{
  if(reviewBusy)return;
  setReviewBusy(true);setReviewError('');
  try{
   const fresh=await save();if(!fresh){setPanel('review');setReviewBusy(false);return;}
   const job=await api('/works/'+w.id+'/'+kind,'POST',{expected_version:fresh.version});
   ctx.watch(job.job_id,undefined,result=>{
    void api('/works/'+w.id).then(accept).catch(reason=>setReviewError(reason.message)).finally(()=>setReviewBusy(false));
    setReviewError(result.status==='failed'?result.error:result.status==='cancelled'?'任务已停止，原稿已保留。':'');
   });
  }catch(reason){setReviewError((reason as Error).message);setReviewBusy(false);setPanel('review');}
 };
 const approve=async(note:string)=>{
  if(dirty||saving||reviewBusy)throw new Error('请先保存修改并等待当前任务完成');
  setReviewBusy(true);
  try{await api('/works/'+w.id+'/approve','POST',{expected_version:w.version,note});accept(await api('/works/'+w.id));}
  finally{setReviewBusy(false);}
 };
 const exportContent=(format:string)=>ctx.action(async()=>{
  const fresh=await save();if(!fresh)return;
  const draftExport=!['passed','manual_passed'].includes(fresh.report.status);
  const response=await fetch(`/api/works/${w.id}/export?format=${format}&draft=${draftExport}&scope=publication`);
  if(!response.ok){const reason=await response.json();throw new Error(reason.detail);}
  const url=URL.createObjectURL(await response.blob()),anchor=document.createElement('a');anchor.href=url;anchor.download=`知客作品-v${fresh.version}.${format}`;anchor.click();URL.revokeObjectURL(url);
 });
 const copy=()=>ctx.action(async()=>{
  const text=[!canExport?'【待检查草稿】':'',publicationCopy(draft,w.brief.platform)].filter(Boolean).join('\n\n');
  if(navigator.clipboard)await navigator.clipboard.writeText(text);
  else ctx.modal.info({title:'复制当前文案',width:720,content:<Input.TextArea readOnly rows={16} value={text}/>});
  setCopied(true);setTimeout(()=>setCopied(false),1800);
 });
 const openSettings=()=>{settingsForm.setFieldsValue(w.brief);setPanel('settings');};
 const recreate=(values:Data)=>ctx.action(async()=>{
  if(!await save())return;bypass.current=true;ctx.navigate('create',JSON.stringify({...w.brief,...values}));
 });
 const draftContent={...w.content,...draft};
 return <div className="writer-workspace" aria-label="作品编辑器">
  <div className="writer-commandbar">
   <div className="writer-location"><Button type="text" icon={<ArrowLeftOutlined/>} onClick={()=>requestEditorNavigation(ctx.onBack)}>作品库</Button><span className="writer-location-divider"/><h1>作品编辑</h1>
    <span className={'writer-save-state '+(error?'has-error':'')} role="status">{saving?'正在保存…':error?'保存遇到问题':dirty?'未保存':'已保存'}</span>
   </div>
   <div className="writer-actions">
    <Button aria-label="保存修改" icon={<SaveOutlined/>} disabled={!dirty||reviewBusy||saving} loading={saving} onClick={()=>void save()}>保存</Button>
    <Button aria-label={'检查内容，'+count+'项待处理'} className={'writer-check '+(canExport?'is-approved':'')} icon={<CheckCircleOutlined/>} loading={reviewBusy} onClick={()=>setPanel('review')}>检查{!canExport&&count>0&&<span className="writer-check-count">{count}</span>}</Button>
    <Button aria-label="创作工具" icon={<ThunderboltOutlined/>} onClick={()=>setPanel('tools')}>创作工具</Button>
    <Dropdown trigger={['click']} menu={{items:[{key:'md',label:canExport?'导出 Markdown':'导出草稿 Markdown'},{key:'txt',label:'导出 TXT'},{key:'html',label:'导出 HTML'},{key:'zip',label:'导出图文 ZIP'}],onClick:({key})=>void exportContent(key)}}><Button type="primary" icon={<DownloadOutlined/>}>导出</Button></Dropdown>
    <Dropdown trigger={['click']} menu={{items:[{key:'preview',label:'预览图文'},{key:'copy',label:'复制当前文案'},{key:'history',label:'版本记录'},{key:'evidence',label:'创作依据'},{key:'settings',label:'作品设置'}],onClick:({key})=>key==='preview'?setPreview(true):key==='copy'?void copy():key==='settings'?openSettings():setPanel(key)}}><Button aria-label="更多作品操作" type="text" icon={<MoreOutlined/>}/></Dropdown>
   </div>
  </div>
  <div className="writer-document-status"><span>{w.brief.platform} · {w.content.product_name}</span><button onClick={()=>setPanel('review')}>{dirty?'已修改，待检查':reviewBusy?'正在检查当前文稿':statuses[w.report.status]||w.report.status}{!canExport&&count?` · ${count}项待确认`:''}</button></div>
  {error&&<Alert className="writer-save-error" showIcon type="error" message={error} action={<Button size="small" onClick={copy}>复制本地草稿</Button>}/>}
  <section className={'writer-paper'+(isMoments?' writer-paper-moments':'')}>
   <RichBodyEditor ref={bodyRef} body={draft.body} images={draft.images} choices={choices} richText={draft.rich_text} disabled={reviewBusy} onChange={change} onImages={()=>setImagesOpen(true)}
    footer={w.brief.platform==='公众号'&&<div className="writer-ending"><span>结尾与行动引导</span><RichTextField field="cta" label="结尾标语" className="writer-cta" value={draft.cta} placeholder="邀请读者咨询、评论或到店体验…"/></div>}>
   <div className="writer-paper-heading"><span className="writer-eyebrow">{w.brief.platform} · {w.content.product_name}</span><div><Button type="text" size="small" icon={<EyeOutlined/>} onClick={()=>setPreview(true)}>预览</Button><Button type="text" size="small" icon={<CopyOutlined/>} onClick={copy}>{copied?'已复制':'复制'}</Button></div></div>
   <RichTextField field="title" label="作品标题" className={isMoments?'writer-title writer-internal-title':'writer-title'} value={draft.title} placeholder="输入一个好标题…"/>
   {isMoments?<p className="writer-platform-hint">上方名称仅用于作品库；复制和发布预览只包含下面的朋友圈正文。</p>:w.brief.platform==='公众号'&&<RichTextField field="intro" label="导语" className="writer-intro" value={draft.intro} placeholder="写一段导语，带读者进入你的故事…"/>}
   </RichBodyEditor>
   {isMoments&&<MomentsGalleryEditor work={w} images={draft.images} dirty={dirty||saving} onManage={()=>setPanel('tools')}/>}
   <div className="writer-tags">{!isMoments&&<Select aria-label="文章标签" mode="tags" variant="borderless" placeholder="添加标签" value={draft.tags} maxCount={10} disabled={reviewBusy} onChange={tags=>change({tags})}/>}<span>{draft.body.replace(/\s/g,'').length} 字</span></div>
  </section>
  <Drawer className="writer-review-drawer" title="检查与确认" width={480} mask={false} open={panel==='review'} onClose={()=>setPanel('')}><ContentReview work={{...w,content:draftContent}} dirty={dirty||saving} busy={reviewBusy} error={reviewError} onCheck={()=>void runReview('verify')} onRepair={()=>void runReview('repair')} onApprove={approve}/>
   <details className="writer-pending-settings"><summary>编辑待确认事项</summary><Select aria-label="待确认事项" mode="tags" value={draft.pending} maxCount={30} disabled={reviewBusy} onChange={pending=>change({pending})}/></details>
  </Drawer>
  <Drawer title="版本记录" width={480} open={panel==='history'} onClose={()=>setPanel('')}><p className="muted">当前为第 {w.version} 版。每次保存和自动调整都会保留记录。</p><div className="writer-history">{w.versions?.map((version:Data)=><button key={version.id} onClick={()=>setHistoryVersion(version)}><span>第 {version.version} 版 <small>{time(version.created_at)}</small></span><b>{version.content.title}</b></button>)}</div>{!w.versions?.length&&<Empty description="暂无历史版本"/>}</Drawer>
  <Modal title={isMoments?'创作工具 · 朋友圈图文':'创作工具 · AI海报'} className="writer-tools-modal" open={panel==='tools'} onCancel={()=>setPanel('')} width={1120} footer={null} styles={{body:{maxHeight:'78vh',overflowY:'auto'}}}>{isMoments?<Tabs defaultActiveKey="gallery" items={[{key:'gallery',label:'朋友圈配图',children:<MomentsGalleryStudio work={w} dirty={dirty||saving} busy={reviewBusy}/>},{key:'poster',label:'AI海报',children:<AiPosterStudio work={w} imageId={posterImageId} dirty={dirty||saving} busy={reviewBusy}/>}]} />:<AiPosterStudio work={w} imageId={posterImageId} dirty={dirty||saving} busy={reviewBusy}/>}</Modal>
  <Modal title="图文预览" open={preview} onCancel={()=>setPreview(false)} width={940} centered styles={{body:{maxHeight:'75vh',overflowY:'auto'}}} footer={null}><ArticlePreview work={w} content={draftContent}/></Modal>
  <Modal title="版本预览" open={!!historyVersion} onCancel={()=>setHistoryVersion(null)} width={940} footer={null}>{historyVersion&&<ArticlePreview work={w} content={historyVersion.content}/>}</Modal>
  <Modal title="创作依据" open={panel==='evidence'} onCancel={()=>setPanel('')} width={940} footer={null}><CompetitionEvidence work={w}/></Modal>
  <Modal title="作品设置" open={panel==='settings'} onCancel={()=>setPanel('')} width={620} footer={null}>
   <Descriptions column={1} size="small" items={[{key:'product',label:'产品型号',children:w.content.product_name}]}/>
   <Form form={settingsForm} layout="vertical" onFinish={recreate} className="writer-settings">
    <Form.Item name="platform" label="发布平台"><Select options={PLATFORM_CHOICES.map(choice=>({value:choice.value,label:choice.value+' · '+choice.label}))}/></Form.Item>
    <Form.Item name="audience" label="目标人群"><Input maxLength={500}/></Form.Item><Form.Item name="scene" label="使用场景"><Input.TextArea rows={3} maxLength={1000}/></Form.Item>
    <Form.Item name="chat_message_ids" label="结合的聊天（可选）"><ChatMaterialPicker/></Form.Item><p className="muted">更换平台、人群或场景会创建新作品，当前文稿会保留。</p><Button type="primary" htmlType="submit" icon={<SettingOutlined/>}>按新设置重新创作</Button>
   </Form>
  </Modal>
  <Modal title="插入配图" open={imagesOpen} onCancel={()=>setImagesOpen(false)} width={780} styles={{body:{maxHeight:'65vh',overflowY:'auto'}}} footer={<Button onClick={()=>setImagesOpen(false)}>完成</Button>}>
   <WorkImageLibrary workId={w.id} choices={choices} selected={draft.images} disabled={reviewBusy}
    onUploaded={image=>{setUploads(items=>[...items,image]);setPendingImages(items=>[...items,image]);}}
    onSelect={image=>{draft.images.some((item:Data)=>item.id===image.id)?bodyRef.current?.removeImage(image.id):draft.images.length<6&&bodyRef.current?.insertImage(image);}}/>
  </Modal>
 </div>;
}
