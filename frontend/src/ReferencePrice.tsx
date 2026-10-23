import React, {useId, useState} from 'react';
import {Modal} from 'antd';
import {Data} from './api';

const productAliases:Record<string,string>={'HUAWEI MateBook Pro':'HUAWEI MateBook Pro（鸿蒙版）'};
const productKey=(name:string)=>(productAliases[name] || name).replace(/\s+/g,'').toLowerCase();
const money=(value:number)=>new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(value);

export function snapshotTime(value:string):string {
  // Preserve date-only records without inventing a time zone or a time of day.
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const date=new Date(value+'T00:00:00Z');
    return !Number.isNaN(date.valueOf()) && date.toISOString().slice(0,10)===value ? value : '';
  }
  if (!/T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return '';
  const date=new Date(value);
  return Number.isNaN(date.valueOf()) ? '' : new Intl.DateTimeFormat('sv-SE',{
    timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false,
  }).format(date);
}

function officialSource(value:string):string|undefined {
  try {
    const url=new URL(value);
    if (url.protocol==='https:' && ['huawei.com','vmall.com'].some(domain=>url.hostname===domain || url.hostname.endsWith('.'+domain))) return url.href;
  } catch { /* Missing or invalid source is not a usable price reference. */ }
}

function priceRank(row:Data):number {
  if (/商城.*(?:页面价|活动页价)/.test(row['价格类型'])) return /专区默认/.test(row['精确款式']) ? 1 : 0;
  if (/预估|搭配购|加购/.test(row['价格类型'])) return 2;
  return 3;
}

export function referencePrices(productName:string,rows:Data[]) {
  const matched=rows.filter(row=>productKey(row['规范产品名称'] || '')===productKey(productName));
  const entries=matched.filter(row=>{
    const raw=String(row['页面金额（元）'] ?? '').trim();
    return /^\d+(?:\.\d{1,2})?$/.test(raw) && Number(raw)>0 && snapshotTime(row['核验时间'] || '') && officialSource(row['官方URL'] || '') && row['精确款式'] && row['价格类型'];
  }).map((row):Data & {amount:number}=>({...row,amount:Number(row['页面金额（元）'])})).sort((a,b)=>
    priceRank(a)-priceRank(b) || Date.parse(b['核验时间'])-Date.parse(a['核验时间']) || a.amount-b.amount);
  return {matched,entries};
}

export function referenceReply(productName:string,row:Data):string {
  const amount=String(row['页面金额（元）']);
  return `${productName}（${row['精确款式']}）的${row['价格类型']}快照为 ¥${amount}${/起价/.test(row['价格类型'])?' 起':''}，核验日期 ${snapshotTime(row['核验时间'])}。这是公开历史参考记录，适用条件尚待当日核验，实际门店价格、优惠资格与库存还需确认。`;
}

export function ReferencePrice({productName,prices,onAdopt}:{productName:string;prices:Data[];onAdopt?:(text:string)=>void}) {
  const {matched,entries}=referencePrices(productName,prices);
  const [selection,setSelection]=useState('');
  const [open,setOpen]=useState(false);
  const selectId=useId();
  const selected=entries.find(row=>row['记录ID']===selection) || entries[0];
  const latest=[...matched].filter(row=>snapshotTime(row['核验时间'] || '')).sort((a,b)=>Date.parse(b['核验时间'])-Date.parse(a['核验时间']))[0];
  const time=snapshotTime((selected || latest)?.['核验时间'] || '');
  const source=officialSource((selected || latest)?.['官方URL'] || '');
  const historical=selected && /参考起价|发布价/.test(selected['价格类型']);
  const label=historical?'历史参考价':/预估/.test(selected?.['价格类型'] || '')?'预估参考价':/搭配购|加购/.test(selected?.['价格类型'] || '')?'搭配参考价':'参考价';
  const delisted=matched.some(row=>/下架/.test(row['库存状态'] || '') && (!selected || Date.parse(row['核验时间'])>=Date.parse(selected['核验时间'])));
  return <><section className="consult-reference-price" aria-label="产品参考价">
    <div className="reference-price-line"><span>{label}</span>{selected ? <strong title={selected['精确款式']}>¥{money(selected.amount)}{/起价/.test(selected['价格类型']) && <small>起</small>}</strong> : <strong className="reference-price-unavailable">价格待咨询</strong>}</div>
    <div className="reference-price-meta">{time && <span title={'北京时间 '+time}>快照 <time dateTime={(selected || latest)['核验时间']}>{time.slice(0,10)}</time></span>}{matched.length>0 && <button type="button" onClick={()=>setOpen(true)}>价格详情</button>}</div>
    {onAdopt&&selected&&<><p className="reference-price-variant">{selected['精确款式']}</p><button className="adopt-reference" type="button" onClick={()=>onAdopt(referenceReply(productName,selected))}>采用参考价回复</button></>}
  </section>
  <Modal open={open} title="价格详情" footer={null} onCancel={()=>setOpen(false)} width={560}>
    <div className="reference-price-detail">
    <h3>{productName}</h3>
    {selected && <p><b>{label} ¥{money(selected.amount)}{/起价/.test(selected['价格类型'])?' 起':''}</b></p>}
    {time && <p>快照日期（北京时间）：{time}</p>}
    {selected && <>
      <p className="reference-price-variant">对应款式：{selected['精确款式']}</p>
      {entries.length>1 && <div className="reference-price-picker"><label htmlFor={selectId}>切换配置或价格记录</label><select id={selectId} value={selected['记录ID']} onChange={event=>setSelection(event.target.value)}>{entries.map(row=><option key={row['记录ID']} value={row['记录ID']}>¥{money(row.amount)} · {row['精确款式']} · {row['价格类型']} · {snapshotTime(row['核验时间'])}</option>)}</select></div>}
      <p>记录口径：{selected['价格类型']}</p>
      {delisted && historical && <p className="reference-price-status">快照中原商城商品页已下架，此金额仅作历史参考。</p>}
      <dl>{[['条件摘要','当时条件'],['库存状态','当时库存'],['地区上下文','地区'],['登录状态','账号条件'],['核验状态','记录说明']].map(([key,label])=>selected[key] && <div key={key}><dt>{label}</dt><dd>{selected[key]}</dd></div>)}</dl>
      <p>原始核验时间：{selected['核验时间']}</p>
    </>}
    {!selected && latest && <p className="reference-price-status">快照记录：{latest['库存状态'] || latest['价格类型']}</p>}
    {source && <a className="reference-price-source" href={source} target="_blank" rel="noreferrer">查看官方来源 ↗</a>}
    <p className="reference-price-notice">仅供选购参考，实际价格、优惠资格与库存以当日确认结果为准。</p>
    </div>
  </Modal></>;
}
