import {useCallback,useEffect,useRef,useState} from 'react';
import {api,ApiError,Data} from './api';

export function toDraft(work:Data):Data{
 const c=work.content;
 const rich_text=Object.fromEntries(Object.entries(c.rich_text||{}).filter(([field,value])=>(value as Data).source===c[field]));
 return {title:c.title||'',intro:c.intro||'',body:c.body||'',cta:c.cta||'',tags:c.tags||[],pending:c.pending||[],images:c.images||[],rich_text};
}
const signature=(value:Data)=>JSON.stringify({...value,images:value.images.map((im:Data)=>({id:im.id,after_block:im.after_block}))});

export function useWorkDraft(initial:Data,suspended=false){
 const [work,setWork]=useState(initial),[draft,setDraft]=useState(()=>toDraft(initial));
 const [saving,setSaving]=useState(false),[error,setError]=useState(''),[savedSignature,setSavedSignature]=useState(()=>signature(toDraft(initial)));
 const state=useRef({work:initial,draft:toDraft(initial),saved:signature(toDraft(initial))});
 const promise=useRef<Promise<Data|null>|null>(null),conflict=useRef(false),mounted=useRef(true);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
 const dirty=signature(draft)!==savedSignature;
 const change=useCallback((patch:Data)=>{
  state.current.draft={...state.current.draft,...patch};setDraft(state.current.draft);
  if(!conflict.current)setError('');
 },[]);
 const accept=useCallback((fresh:Data)=>{
  const value=toDraft(fresh),sig=signature(value);state.current={work:fresh,draft:value,saved:sig};conflict.current=false;
  if(mounted.current){setWork(fresh);setDraft(value);setSavedSignature(sig);setError('');}
 },[]);
 const save=useCallback(():Promise<Data|null>=>{
  if(promise.current)return promise.current;
  if(conflict.current)return Promise.resolve(null);
  const snapshot=state.current.draft,sig=signature(snapshot),previous=state.current.work;
  if(sig===state.current.saved)return Promise.resolve(previous);
  if(!snapshot.title.trim()||!snapshot.body.trim()){
   setError('请填写标题和正文，修改仍保留在编辑器中。');return Promise.resolve(null);
  }
  setSaving(true);setError('');
  const request=(async()=>{
   try{
    const {images,...content}=snapshot;
    await api('/works/'+previous.id,'PATCH',{...content,expected_version:previous.version,
     image_ids:images.map((im:Data)=>im.id),image_positions:Object.fromEntries(images.map((im:Data)=>[im.id,im.after_block??0]))});
    // Advance the known version even if the subsequent refresh temporarily fails.
    state.current.work={...previous,version:previous.version+1,content:{...previous.content,...snapshot},report:{status:'unchecked'}};
    state.current.saved=sig;
    if(mounted.current){setWork(state.current.work);setSavedSignature(sig);}
    const fresh=await api('/works/'+previous.id);
    if(signature(state.current.draft)===sig)accept(fresh);
    else{state.current.work=fresh;if(mounted.current)setWork(fresh);}
    return fresh;
   }catch(reason){
    if(reason instanceof ApiError&&reason.status===409)conflict.current=true;
    if(mounted.current)setError((reason as Error).message+'；本地修改已保留。');
    return null;
   }finally{promise.current=null;if(mounted.current)setSaving(false);}
  })();
  promise.current=request;return request;
 },[accept]);
 useEffect(()=>{
  if(!dirty||saving||error||suspended)return;
  const timer=setTimeout(()=>void save(),1800);return()=>clearTimeout(timer);
 },[draft,dirty,saving,error,suspended,save]);
 useEffect(()=>{
  const leave=(event:BeforeUnloadEvent)=>{if(dirty||saving){event.preventDefault();event.returnValue='';}};
  window.addEventListener('beforeunload',leave);return()=>window.removeEventListener('beforeunload',leave);
 },[dirty,saving]);
 return {work,draft,dirty,saving,error,change,save,accept};
}
