import {workImageUrl} from './workImages';
import React from 'react';
import {Data} from './api';
import {ArticleBody} from './CompetitionEvidence';
import {RichTextContent,richDocument} from './richText';
import './platformPreview.css';
import {MomentsGalleryFeed,MomentsGalleryGrid} from './MomentsGallery';

export function publicationCopy(content:Data,platform:string){
 if(platform==='朋友圈')return content.body||'';
 return [content.title,content.intro,content.body,content.cta,content.tags?.map((tag:string)=>'#'+tag.replace(/^#+/,'')).join(' ')].filter(Boolean).join('\n\n');
}
export function PlatformArticlePreview({work,content}:{work:Data;content:Data}){
 const platform=work.brief.platform;
 const field=(key:'title'|'intro'|'cta')=>richDocument(content,key)?<RichTextContent doc={richDocument(content,key)!} inline/>:content[key];
 if(platform==='朋友圈'){
  const fallback=content.images?.length?<MomentsGalleryGrid items={content.images.slice(0,9).map((image:Data)=>({kind:'original',image_id:image.id,title:image.caption||image.description||image.name,url:workImageUrl(image.id)}))}/>:null;
  return <article className="platform-moments" aria-label="朋友圈发布预览"><div className="platform-moments-author">知客 · 门店分享</div><ArticleBody content={{...content,images:[]}}/>{work.id?<MomentsGalleryFeed work={work} content={content} fallback={fallback}/>:fallback}</article>;
 }
 return <article className={'article writer-preview '+(platform==='公众号'?'platform-wechat':'platform-rednote')}>
  <div className="eyebrow">{platform} · {work.content?.product_name||content.product_name}</div>
  <h1>{field('title')}</h1>{content.intro&&<p className="article-intro">{field('intro')}</p>}
  <ArticleBody content={content}/>{content.cta&&<p className="article-cta">{field('cta')}</p>}
  {!!content.tags?.length&&<div className="platform-hashtags">{content.tags.map((tag:string)=><span key={tag}>#{tag.replace(/^#+/,'')}</span>)}</div>}
 </article>;
}
