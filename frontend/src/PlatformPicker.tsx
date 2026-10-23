import React from 'react';
export const PLATFORM_CHOICES=[
 {value:'公众号',label:'深度文章',description:'解释选择逻辑，分节讲清依据与适用边界',output:'标题 · 导语 · 分节正文 · 穿插配图',button:'生成公众号文章'},
 {value:'小红书',label:'场景笔记',description:'从真实使用场景切入，提供可收藏的建议',output:'口语标题 · 短段落与清单 · 话题配图',button:'生成小红书笔记'},
 {value:'朋友圈',label:'自然短文',description:'像门店顾问与朋友聊天，搭配真实产品与场景图片',output:'自然短文 · 单图/三图/六图/九宫格',button:'生成朋友圈图文'},
];
export function PlatformPicker({value,onChange}:{value?:string;onChange?:(value:string)=>void}){
 return <div className="platform-picker" role="radiogroup" aria-label="发布平台">{PLATFORM_CHOICES.map(choice=><button key={choice.value} type="button" role="radio" aria-checked={value===choice.value} className={value===choice.value?'is-selected':''} onClick={()=>onChange?.(choice.value)}><span>{choice.value}<b>{choice.label}</b></span><p>{choice.description}</p><small>{choice.output}</small></button>)}</div>;
}
