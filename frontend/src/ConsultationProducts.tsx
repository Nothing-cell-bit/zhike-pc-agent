import React, {useEffect, useState} from 'react';
import {Button, Modal} from 'antd';
import {ArrowLeftOutlined, ArrowRightOutlined, PauseOutlined, CaretRightOutlined, PictureOutlined, ShopOutlined} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import {Data} from './api';
import {useData} from './lifecycle';
import {ReferencePrice} from './ReferencePrice';

const normalize = (value:string) => value.toLowerCase().replace(/huawei|华为/g, '').replace(/[\s（）()™®]/g, '');

// Only a unique model/version or a product card can pin the display. A broad
// mention such as “Mate” must not silently select a particular computer.
export function consultedProduct(products:Data[], messages:Data[]):Data|undefined {
  for (const message of [...messages].reverse()) {
    const card = products.find(p => p.id === message.card?.product_id);
    if (card) return card;
    const text = normalize(message.content || '');
    const matches = products.map(p => {
      const full = normalize(p.name);
      const model = normalize(p.name.split(/[（(]|\s+酷睿|\s+20\d{2}/)[0]);
      const aliases = [full, model].filter(alias => alias.length >= 6);
      const alias = aliases.filter(alias => {
        const index = text.indexOf(alias);
        return index >= 0 && !/[a-z0-9]/.test(text[index + alias.length] || '');
      }).sort((a,b)=>b.length-a.length)[0] || '';
      return {product:p, alias, length:alias.length};
    }).filter(match => match.length > 0);
    if (matches.length) {
      // Keep separate models ambiguous; discard only shorter prefix matches.
      const specific = matches.filter(match => !matches.some(other => other.length > match.length && other.alias.startsWith(match.alias)));
      return specific.length === 1 ? specific[0].product : undefined;
    }
  }
}

export function factSections(body:string):{title:string;body:string}[] {
  return body.split(/^##\s+/m).slice(1).map(section => {
    const [title, ...lines] = section.split('\n');
    return {title:title.trim(), body:lines.join('\n').trim()};
  }).filter(section => ['操作系统','处理器','内存','存储'].includes(section.title) && section.body).slice(0,3);
}

function ProductImage({src,name}:{src?:string;name:string}) {
  const [failed,setFailed] = useState(false);
  return src && !failed ? <img src={src} alt={name} onError={()=>setFailed(true)}/> : <div className="consult-image-empty"><PictureOutlined/><span>产品图片待补充</span></div>;
}

function ProductInformation({product,onAsk,disabled}:{product:Data;onAsk:(name:string)=>void;disabled:boolean}) {
  const {data,error,refresh} = useData('/products/'+encodeURIComponent(product.id));
  const [open,setOpen] = useState(false);
  const sections = factSections(data?.facts?.body || '');
  return <>
    <div className="consult-product-photo"><ProductImage key={product.cover || product.id} src={product.cover} name={product.name}/><span className="consult-photo-label">产品实图</span></div>
    <div className="consult-product-copy">
      <span className="consult-brand">HUAWEI · 华为电脑</span>
      <h3 title={product.name}>{product.name.replace(/^HUAWEI\s*/, '')}</h3>
      <div className="consult-product-details" role="region" aria-label="产品价格与参数" tabIndex={0}>
      {data && <ReferencePrice productName={product.name} prices={data.prices || []}/>}
      <div className="consult-product-facts">
        {!data && !error && <p role="status">正在加载产品资料…</p>}
        {error && <p role="status">产品资料暂时未能加载 <button onClick={()=>void refresh()}>重试</button></p>}
        {sections.map(section=><div key={section.title}><span>{section.title}</span><div><ReactMarkdown>{section.body}</ReactMarkdown></div></div>)}
        {data && sections.length===0 && <p>详细配置与功能，请查看产品资料或向顾问咨询。</p>}
      </div>
      </div>
      <p className="consult-price-note">具体配置以销售版本为准，价格与库存请咨询顾问。</p>
      <div className="consult-product-actions"><Button type="primary" disabled={disabled} onClick={()=>onAsk(product.name)}>聊聊这款产品 <ArrowRightOutlined/></Button><Button type="text" disabled={!data} onClick={()=>setOpen(true)}>查看详细资料</Button></div>
    </div>
    <Modal open={open} title={product.name} footer={null} onCancel={()=>setOpen(false)} width={760}><div className="prose"><ReactMarkdown>{data?.facts?.body || '暂无详细资料'}</ReactMarkdown></div></Modal>
  </>;
}

export function ConsultationProducts({products,messages,onAsk,disabled=false}:{products:Data[];messages:Data[];onAsk:(name:string)=>void;disabled?:boolean}) {
  const pinned = consultedProduct(products,messages);
  const [index,setIndex] = useState(0);
  const [paused,setPaused] = useState(false);
  const [hovered,setHovered] = useState(false);
  const [focused,setFocused] = useState(false);
  const [reducedMotion,setReducedMotion] = useState(false);
  useEffect(()=>{
    const query=window.matchMedia?.('(prefers-reduced-motion: reduce)');
    if (!query) return;
    const update=()=>setReducedMotion(query.matches);
    update();query.addEventListener('change',update);
    return ()=>query.removeEventListener('change',update);
  },[]);
  const rotating = !pinned && products.length > 1;
  useEffect(()=>{
    if (!rotating || paused || hovered || focused || reducedMotion) return;
    const timer=setInterval(()=>setIndex(current=>(current+1)%products.length),7000);
    return ()=>clearInterval(timer);
  },[rotating,paused,hovered,focused,reducedMotion,products.length]);
  const active = pinned || products[index % products.length];
  const move=(step:number)=>{setPaused(true);setIndex(current=>(current+step+products.length)%products.length);};
  return <aside className="consult-products" aria-label="咨询相关产品" onMouseEnter={()=>setHovered(true)} onMouseLeave={()=>setHovered(false)} onFocusCapture={()=>setFocused(true)} onBlurCapture={event=>{if(!event.currentTarget.contains(event.relatedTarget))setFocused(false);}}>
    <header className="consult-products-heading"><div><span className="consult-heading-icon"><ShopOutlined/></span><div><h2>{pinned?'正在聊的产品':'发现店内好物'}</h2><p>{pinned?'跟随咨询，了解产品细节':'边聊边逛，找到适合你的电脑'}</p></div></div><span className={'consult-mode '+(pinned?'is-pinned':'')}>{pinned?'当前咨询':'店内轮播'}</span></header>
    {active ? <ProductInformation key={active.id} product={active} onAsk={onAsk} disabled={disabled}/> : <div className="consult-products-empty"><ShopOutlined/><h3>产品资料准备中</h3><p>你可以先告诉顾问预算和使用需求。</p></div>}
    {rotating && <div className="consult-carousel-controls"><Button type="text" icon={<ArrowLeftOutlined/>} aria-label="上一款产品" onClick={()=>move(-1)}/><span>{String(index % products.length+1).padStart(2,'0')} <span>/ {String(products.length).padStart(2,'0')}</span></span><Button type="text" icon={<ArrowRightOutlined/>} aria-label="下一款产品" onClick={()=>move(1)}/>{!reducedMotion && <Button type="text" icon={paused?<CaretRightOutlined/>:<PauseOutlined/>} aria-label={paused?'播放产品轮播':'暂停产品轮播'} onClick={()=>setPaused(value=>!value)}/>}</div>}
    <footer className="consult-products-footer"><span/> {pinned?'产品信息来自门店资料库':'提到具体型号后，这里会展示相关产品'}</footer>
  </aside>;
}
