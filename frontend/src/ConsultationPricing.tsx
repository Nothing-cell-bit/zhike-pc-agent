import React,{useState} from 'react';
import {Alert,Button,Collapse,Modal,Select,Spin} from 'antd';
import {Data} from './api';
import {useData} from './lifecycle';
import {consultedProduct} from './ConsultationProducts';
import {ReferencePrice} from './ReferencePrice';

type Props={products:Data[];messages:Data[];selectedProduct:string;onSelect:(id:string)=>void;editable:boolean;onAdopt:(text:string)=>void;onGenerate:(id:string)=>void;plan?:Data;loading?:boolean;compact?:boolean};
export function ConsultationPricing(props:Props){
 const [open,setOpen]=useState(false);
 const selected=props.products.find(p=>p.id===props.selectedProduct)||consultedProduct(props.products,props.messages);
 const plan=props.plan?.product_id===selected?.id?props.plan:undefined;
 const content=<section className="staff-pricing" aria-label="价格与方案">
  <div className="section-title compact"><h3>价格与方案</h3><Button size="small" onClick={()=>setOpen(true)}>四级报价详情</Button></div>
  <Select aria-label="报价产品型号" placeholder="请先选择具体型号" value={selected?.id} onChange={props.onSelect} options={props.products.map(p=>({value:p.id,label:p.name}))} showSearch optionFilterProp="label"/>
  {selected?<ProductPrice key={selected.id} product={selected} onAdopt={props.editable?props.onAdopt:undefined}/>:<p className="muted">选择后可查看对应配置和参考价。</p>}
  <Modal title="四级报价详情" open={open} onCancel={()=>setOpen(false)} footer={null} width={720}>
   <p>{selected?.name||'请先选择具体型号'}</p>
   <p className="muted">按单机、资格优惠、套装、专项审批整理。具体金额须有对应配置、已确认的规则和有效期。</p>
   <Button loading={props.loading} disabled={!selected||!props.editable} onClick={()=>selected&&props.onGenerate(selected.id)}>{plan?'重新整理方案':'从 ima 整理方案'}</Button>
   {plan&&<div className="pricing-levels"><Alert type="info" message="方案详情已整理，门店金额及适用条件待确认"/>
    <Collapse items={(plan.levels||[]).map((level:Data)=>({key:level.level,label:<span>{level.title}<small> · {level.status_label}</small></span>,children:<><p>{level.description}</p>{level.items?.length?<ul>{level.items.map((item:Data,index:number)=><li key={index}><span>{item.text}</span><small>{item.source_title}</small></li>)}</ul>:<p>当前资料不足，需补充此类报价规则。</p>}</>}))}/>
    <details><summary>资料来源</summary><ul>{(plan.sources||[]).map((source:Data)=><li key={source.id}>{source.title}</li>)}</ul></details>
   </div>}
  </Modal>
 </section>;
 return props.compact?<details className="secondary-pricing"><summary>历史参考价与报价核对</summary>{content}</details>:content;
}
function ProductPrice({product,onAdopt}:{product:Data;onAdopt?:Props['onAdopt']}){
 const {data,error}=useData('/products/'+encodeURIComponent(product.id));
 return error?<Alert type="error" message="参考价格暂时无法读取，请稍后重试"/>:data?<ReferencePrice productName={product.name} prices={data.prices||[]} onAdopt={onAdopt}/>:<Spin size="small"/>;
}
