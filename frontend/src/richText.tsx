import {workImageUrl} from './workImages';
import React from 'react';
import {Data} from './api';
import type {JSONContent} from '@tiptap/core';

export type TextField='title'|'intro'|'body'|'cta';
export type RichTextMap=Partial<Record<TextField,{source:string;doc:JSONContent}>>;
export const validFont=(font:string)=>/^[\p{L}\p{N} _,-]{1,80}$/u.test(font);
export function textStyle(attrs:Data={}):React.CSSProperties{
 return {fontFamily:validFont(attrs.fontFamily||'')?attrs.fontFamily:undefined,
  fontSize:/^(?:[1-8]\d|9[0-6])px$/.test(attrs.fontSize||'')?attrs.fontSize:undefined};
}
export function richDocument(content:Data,field:TextField):JSONContent|undefined{
 const rich=content.rich_text?.[field];return rich?.source===content[field]&&rich?.doc?.type==='doc'?rich.doc:undefined;
}
export function RichTextContent({doc,images=[],inline=false}:{doc:JSONContent;images?:Data[];inline?:boolean}){
 const render=(node:JSONContent,key:number):React.ReactNode=>{
  const children=node.content?.map(render);
  if(node.type==='text')return <React.Fragment key={key}>{(node.marks||[]).reduce<React.ReactNode>((child,mark)=>{
   if(mark.type==='bold')return <strong>{child}</strong>;
   if(mark.type==='italic')return <em>{child}</em>;
   if(mark.type==='strike')return <s>{child}</s>;
   if(mark.type==='code')return <code>{child}</code>;
   if(mark.type==='textStyle')return <span style={textStyle(mark.attrs)}>{child}</span>;
   if(mark.type==='link'&&/^https?:\/\//i.test(mark.attrs?.href||''))return <a href={mark.attrs?.href} rel="noreferrer">{child}</a>;
   return child;
  },node.text)}</React.Fragment>;
  if(node.type==='hardBreak')return <br key={key}/>;
  if(node.type==='horizontalRule')return <hr key={key}/>;
  if(node.type==='productImage'){
   const image=images.find(image=>image.id===node.attrs?.id);if(!image)return null;
   return <figure key={key}><img src={workImageUrl(image.id)} alt={image.caption||image.name}/><figcaption>{image.caption||image.description}</figcaption></figure>;
  }
  if(node.type==='doc')return <React.Fragment key={key}>{children}</React.Fragment>;
  if(inline)return <span key={key}>{key>0&&<br/>}{children}</span>;
  const tags:Record<string,string>={paragraph:'p',heading:'h'+Math.min(3,Math.max(1,node.attrs?.level||2)),bulletList:'ul',orderedList:'ol',listItem:'li',blockquote:'blockquote',codeBlock:'pre',horizontalRule:'hr'};
  return React.createElement(tags[node.type||'']||'div',{key,...(node.type==='orderedList'?{start:node.attrs?.start||1}:{})},children);
 };
 return <>{render(doc,0)}</>;
}
