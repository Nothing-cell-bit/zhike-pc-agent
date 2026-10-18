import React from 'react';
import {Button,Tag} from 'antd';
import {EditOutlined} from '@ant-design/icons';
import {Data} from './api';

export const NEED_FIELDS:Record<string,{label:string;hint:string}>={
 user:{label:'客户身份',hint:'实际使用者、年级或职业'},
 progress:{label:'购机意向',hint:'新购、换机或帮人选购，以及目前的购机打算'},
 budget:{label:'购机预算',hint:'金额、范围或最高预算，保留“以内”“左右”等限制'},
 tasks:{label:'主要用途',hint:'电脑具体用来做什么，可填写多项'},
 software:{label:'必用软件',hint:'必须运行的软件或游戏名称'},
 concerns:{label:'主要顾虑',hint:'客户明确提出的担忧、要求或取舍'},
 next_step:{label:'下一步安排',hint:'客户已同意的后续动作和时间'},
};
export function knownNeed(value:unknown){
 const text=typeof value==='string'?value.trim():'';
 return ['','待确认','待了解','未提及','未知','尚未了解','未明确','unknown'].includes(text.toLowerCase())?'':text;
}
type Props={analysis:Data;editable:boolean;updating?:boolean;onEdit:(field:string,value:string)=>void;onAdopt:(text:string)=>void};

export function CustomerNeeds({analysis,editable,updating=false,onEdit,onAdopt}:Props){
 const question=analysis.next_question;
 return <>
  <div className="section-title compact"><h3>客户需求</h3>{updating&&<Tag>更新中</Tag>}</div>
  {question&&question.state!=='paused'&&<section className="next-question question-card" aria-label="下一句建议"><b>下一句建议</b><p>{updating?'正在根据新消息更新建议。':question.text}</p>{!updating&&question.state==='ready'&&question.text&&<Button block size="small" disabled={!editable} onClick={()=>onAdopt(question.text)}>采用到输入框</Button>}</section>}
  {Object.entries(NEED_FIELDS).map(([key,field])=>{
   const value=knownNeed(analysis[key]?.value);
   return <div className="insight" key={key}><div><small>{field.label}</small><Button type="text" size="small" aria-label={'修改'+field.label} disabled={!editable} icon={<EditOutlined/>} onClick={()=>onEdit(key,value)}/></div><p className={value?'':'unknown-need'}>{value||'尚未了解'}</p>{analysis[key]?.manual&&<Tag>已手动确认</Tag>}{analysis[key]?.status==='partial'&&<Tag>待明确</Tag>}</div>;
  })}
 </>;
}
