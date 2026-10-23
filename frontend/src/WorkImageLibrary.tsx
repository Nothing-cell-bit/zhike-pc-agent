import React,{useRef,useState} from 'react';
import {Alert,Button,Empty} from 'antd';
import {UploadOutlined} from '@ant-design/icons';
import {Data} from './api';
import {uploadWorkImage,workImageUrl} from './workImages';

type Props={workId:string;choices:Data[];selected:Data[];disabled:boolean;
 onSelect:(image:Data)=>void;onUploaded:(image:Data)=>void};

export function WorkImageLibrary({workId,choices,selected,disabled,onSelect,onUploaded}:Props){
 const input=useRef<HTMLInputElement>(null),busy=useRef(false);
 const [uploading,setUploading]=useState(false),[error,setError]=useState(''),[dragging,setDragging]=useState(false);
 const full=selected.length>=6;
 const upload=async(files:File[])=>{
  if(disabled||busy.current||full||!files.length)return;
  if(files.length>6-selected.length){setError(`文稿最多插入6张图片，目前还可插入${6-selected.length}张`);return;}
  busy.current=true;setUploading(true);setError('');
  try{
   for(const file of files){
    try{onUploaded(await uploadWorkImage(workId,file));}
    catch(reason){setError(file.name+'：'+(reason as Error).message);break;}
   }
  }finally{busy.current=false;setUploading(false);if(input.current)input.current.value='';}
 };
 return <div>
  <div className={'writer-local-upload '+(dragging?'is-dragging':'')} onDragOver={event=>{event.preventDefault();setDragging(true);}} onDragLeave={()=>setDragging(false)} onDrop={event=>{event.preventDefault();setDragging(false);void upload(Array.from(event.dataTransfer.files));}}>
   <input ref={input} type="file" multiple accept="image/jpeg,image/png,image/webp" aria-label="选择本地图片" hidden disabled={disabled||uploading||full} onChange={event=>void upload(Array.from(event.target.files||[]))}/>
   <Button icon={<UploadOutlined/>} loading={uploading} disabled={disabled||full} onClick={()=>input.current?.click()}>{uploading?'正在上传图片…':'本地上传'}</Button>
   <span>{full?'已插入6张，移除一张后可继续上传':'也可将图片拖到这里 · JPG / PNG / WebP · 每张不超过10MB'}</span>
  </div>
  <p className="muted">上传后自动插入正文光标处；可在正文拖动调整位置。已选 {selected.length}/6 张。</p>
  {error&&<Alert showIcon type="error" message={error} className="writer-upload-error"/>}
  <div className="writer-image-library">{[...choices].sort((a,b)=>Number(b.source_type==='user_upload')-Number(a.source_type==='user_upload')).map(image=>{
   const picked=selected.some(item=>item.id===image.id);
   return <button type="button" key={image.id} className={picked?'is-selected':''} disabled={disabled||uploading||(!picked&&full)} onClick={()=>onSelect(image)}>
    <img src={workImageUrl(image.id)} alt={image.caption||image.description||image.name}/>
    <small>{image.source_type==='user_upload'?'本地上传':'产品资料原图'}</small>
    <span>{picked?'已选 · 点击移除':'插入配图'}</span>
   </button>;
  })}</div>
  {!choices.length&&<Empty description="还没有配图，可以从本地上传"/>}
 </div>;
}
