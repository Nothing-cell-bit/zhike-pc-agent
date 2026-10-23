import React from 'react';
import {Data} from './api';
const labels:Record<string,string>={L1:'单机标准',L2:'资格优惠',L3:'套装方案',L4:'审批专项'};
const money=(minor:number)=>(minor/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
export function QuoteCard({card}:{card:Data}){
 return <section className="message-quote" aria-label="门店报价">{(card.quotes||[]).map((q:Data,i:number)=><div className="message-quote-item" key={i}>
  <small>{q.is_demo?'【演示测试报价，非门店售价】 · ':''}{labels[q.level]||'门店报价'} · 含税</small><b>{q.name}</b><p>{q.variant}</p>
  <dl><div><dt>销售型号</dt><dd>{q.sku_ref}</dd></div><div><dt>数量</dt><dd>{q.quantity} 台</dd></div>
   <div><dt>单价</dt><dd>¥{money(q.unit_minor)}</dd></div>{q.fees_minor>0&&<div><dt>附加费用（合计）</dt><dd>¥{money(q.fees_minor)}</dd></div>}
   {q.deduction_minor>0&&<div><dt>优惠（合计）</dt><dd>−¥{money(q.deduction_minor)}</dd></div>}
  </dl><div className="message-quote-total"><span>应付合计</span><strong>¥{money(q.total_minor)}</strong></div>
  {q.components?.length>0&&<ul aria-label="套装明细">{q.components.map((item:Data,index:number)=><li key={index}>{item.name} · {item.sku_ref} × {item.quantity} · ¥{money(item.unit_minor)} / 件</li>)}</ul>}
  <small>有效至 {new Date(q.valid_until).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})}（北京时间）</small>
 </div>)}</section>;
}
