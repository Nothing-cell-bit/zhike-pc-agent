import React,{useEffect,useRef,useState} from 'react';
import {Alert,Button,Checkbox,Empty,Input,Modal,Spin,Tag} from 'antd';
import {MessageOutlined} from '@ant-design/icons';
import {api,Data,time} from './api';
import {useData} from './lifecycle';
import './chatMaterials.css';

type Props={value?:string[];onChange?:(ids:string[])=>void;disabled?:boolean};
export function ChatMaterialPicker({value=[],onChange,disabled=false}:Props){
 const [open,setOpen]=useState(false);
 return <div className="chat-material-picker">
  <div className="chat-material-summary"><Button aria-label="选择聊天素材" icon={<MessageOutlined/>} disabled={disabled} onClick={()=>setOpen(true)}>选择聊天素材</Button><span>{value.length?`已选 ${value.length} 条消息`:'未选择，按创作设置生成'}</span>{!!value.length&&<Button aria-label="清空聊天素材" type="text" disabled={disabled} onClick={()=>onChange?.([])}>清空</Button>}</div>
  <p className="muted">从当前由你接待的聊天中选择具体消息，作为需求、场景和顾虑素材。</p>
  {open&&<ChatSourceDialog initial={value} onClose={()=>setOpen(false)} onConfirm={ids=>{onChange?.(ids);setOpen(false);}}/>}
 </div>;
}

function ChatSourceDialog({initial,onClose,onConfirm}:{initial:string[];onClose:()=>void;onConfirm:(ids:string[])=>void}){
 const sources=useData('/marketing/chat-sources'),[active,setActive]=useState(''),[query,setQuery]=useState(''),[selected,setSelected]=useState(initial);
 useEffect(()=>{if(!active&&sources.data?.length)setActive(sources.data[0].id);},[sources.data,active]);
 const chats:Data[]=(sources.data||[]).filter((item:Data)=>(item.name+item.stage).includes(query));
 const toggle=(id:string)=>setSelected(items=>items.includes(id)?items.filter(item=>item!==id):items.length<20?[...items,id]:items);
 return <Modal title="选择聊天素材" open width={1000} onCancel={onClose} className="chat-source-modal" footer={<div className="chat-source-footer"><span>已选 {selected.length}/20 条</span><Button onClick={()=>setSelected([])}>清空选择</Button><Button aria-label="取消选择" onClick={onClose}>取消</Button><Button aria-label="使用所选素材" type="primary" onClick={()=>onConfirm(selected)}>使用所选素材</Button></div>}>
  <p className="chat-source-note">AI仅使用勾选的消息，不会自动带入整段聊天。客户姓名和常见联系方式已脱敏；每条最多取前1000字，下面显示的摘录将用于生成。</p>
  {sources.error?<Alert type="error" message={sources.error} action={<Button onClick={()=>void sources.refresh()}>重试</Button>}/>:!sources.data?<Spin/>:!sources.data.length?<Empty description="还没有已绑定的聊天。请先在客户接待中认领或接管聊天，再来选择素材。"/>:
   <div className="chat-source-layout"><aside aria-label="已绑定的聊天"><Input aria-label="搜索已绑定聊天" placeholder="搜索客户或接待阶段" value={query} onChange={event=>setQuery(event.target.value)}/><div className="chat-source-conversations">{chats.map(chat=><button type="button" key={chat.id} aria-pressed={active===chat.id} className={active===chat.id?'is-active':''} onClick={()=>setActive(chat.id)}><strong>{chat.name}</strong><span>{chat.stage} · {chat.message_count}条消息</span></button>)}{!chats.length&&<p className="muted">没有匹配的聊天</p>}</div></aside>
    {active&&<ChatMessages key={active} conversationId={active} selected={selected} onToggle={toggle}/>}
   </div>}
 </Modal>;
}

function ChatMessages({conversationId,selected,onToggle}:{conversationId:string;selected:string[];onToggle:(id:string)=>void}){
 const [page,setPage]=useState<Data|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false),mounted=useRef(true);
 const load=async(before?:number)=>{
  setLoading(true);setError('');
  try{const result=await api('/marketing/chat-sources/'+encodeURIComponent(conversationId)+(before?'?before='+before:''));
   if(mounted.current)setPage(previous=>({...result,messages:before?[...result.messages,...(previous?.messages||[])]:result.messages}));
  }catch(reason){if(mounted.current)setError((reason as Error).message);}
  finally{if(mounted.current)setLoading(false);}
 };
 useEffect(()=>{mounted.current=true;void load();return()=>{mounted.current=false;};},[conversationId]);
 return <section className="chat-source-messages" aria-label="聊天消息选择">
  {error&&<Alert type="error" message={error} action={<Button onClick={()=>void load()}>重试</Button>}/>}
  {page?.has_more&&<Button disabled={loading} onClick={()=>void load(page.next_before)}>加载更早消息</Button>}
  {loading&&<Spin/>}
  {page?.messages?.map((message:Data)=><Checkbox className={'chat-source-message '+(selected.includes(message.id)?'is-selected':'')} key={message.id} aria-label={'选择消息 '+message.id} checked={selected.includes(message.id)} disabled={selected.length>=20&&!selected.includes(message.id)} onChange={()=>onToggle(message.id)}>
   <div><div className="chat-source-message-meta"><Tag>{message.role==='customer'?'客户':'顾问'}</Tag><time>{time(message.created_at)}</time></div><p>{message.content}</p>{message.truncated&&<small>较长消息，仅使用前1000字</small>}</div>
  </Checkbox>)}
  {page&&!page.messages?.length&&<Empty description="这个聊天还没有可选的文字消息"/>}
 </section>;
}
