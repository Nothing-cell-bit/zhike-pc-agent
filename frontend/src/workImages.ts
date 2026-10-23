import {ApiError,Data} from './api';

export const workImageUrl=(id:string)=>
 (id.startsWith('upload-')?'/api/assets/':'/api/knowledge/images/')+encodeURIComponent(id);

export const workCoverUrl=(work:Data):string=>work.cover_image?.url||
 (work.content.images?.[0]?.id?workImageUrl(work.content.images[0].id):'');

export async function uploadWorkImage(workId:string,file:File):Promise<Data>{
 if(!/\.(jpe?g|png|webp)$/i.test(file.name))throw new Error('仅支持 JPG、PNG、WebP 图片');
 if(file.size>10*1024*1024)throw new Error('图片不能超过10MB');
 const response=await fetch('/api/works/'+encodeURIComponent(workId)+'/images?filename='+encodeURIComponent(file.name),{
  method:'POST',credentials:'same-origin',headers:{'Content-Type':file.type||'application/octet-stream','X-Store-Request':'1'},body:file,
 });
 const result=await response.json().catch(()=>({}));
 if(!response.ok)throw new ApiError(typeof result.detail==='string'?result.detail:'图片上传失败，请重试',response.status);
 return result;
}
