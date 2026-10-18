import React from 'react';
import {MessageOutlined,EditOutlined,FolderOpenOutlined,RightOutlined,PlusOutlined,FileTextOutlined} from '@ant-design/icons';
import {Data,time} from './api';

const dateKey=(value:Date)=>value.toLocaleDateString('en-CA',{timeZone:'Asia/Shanghai'});
export function followupTime(value:string,now=new Date()){
 const date=new Date(value);
 if(Number.isNaN(date.getTime()))return '时间待安排';
 const day=dateKey(date),today=dateKey(now),tomorrow=dateKey(new Date(now.getTime()+86400000));
 const clock=date.toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hour12:false});
 return day===today?'今天 '+clock:day===tomorrow?'明天 '+clock:time(value);
}
export const pendingFollowups=(items:Data[])=>items.filter(x=>x.status==='pending').sort((a,b)=>Date.parse(a.due_at)-Date.parse(b.due_at));

type Props={summary:Data;productsCount:number;followups:Data[]|null;works:Data[]|null;navigate:(view:string,id?:string)=>void;followupsError?:string;worksError?:string};

export function Home({summary,productsCount,followups,works,navigate,followupsError,worksError}:Props){
 const pending=followups?pendingFollowups(followups).slice(0,3):[];
 const recent=works?[...works].sort((a,b)=>Date.parse(b.updated_at)-Date.parse(a.updated_at)).slice(0,3):[];
 const entries=[{title:'客户接待',count:summary.waiting,unit:'位待接待',detail:'会话与跟进',view:'chat',icon:<MessageOutlined/>},{title:'营销内容',count:summary.works,unit:'份作品',detail:'创作与作品',view:'works',icon:<EditOutlined/>},{title:'产品资料',count:productsCount,unit:'款产品',detail:'参数与图片',view:'products',icon:<FolderOpenOutlined/>}];
 return <div className="home-page">
  <div className="home-heading"><div><h1>工作台</h1><p>{new Date().toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'long',day:'numeric',weekday:'long'}).replace('星期','　星期')}</p></div><button className="home-primary" onClick={()=>navigate('create')}><PlusOutlined/>新建内容</button></div>
  <div className="home-entries">{entries.map(entry=><button key={entry.view} className="home-entry" onClick={()=>navigate(entry.view)}><span className="home-entry-icon">{entry.icon}</span><span className="home-entry-copy"><strong>{entry.title}</strong><span className="home-entry-count"><b>{entry.count??'—'}</b> {entry.unit}</span><small>{entry.detail}</small></span><RightOutlined className="home-entry-arrow"/></button>)}</div>
  <div className="home-sections">
   <section className="home-section" aria-labelledby="home-followups-heading"><header><h2 id="home-followups-heading">待办跟进</h2><button className="home-link" onClick={()=>navigate('followups')}>查看全部 <RightOutlined/></button></header>
    {followupsError?<p className="home-empty" role="alert">跟进暂时加载失败，请稍后重试。</p>:followups===null?<p className="home-empty" role="status">正在加载跟进…</p>:pending.length?<ul className="home-rows">{pending.map((item,index)=><li key={item.id}><span className={'home-avatar tint-'+index}>{item.customer_name?.slice(0,1)||'客'}</span><div className="home-row-copy"><strong title={item.customer_name+' · '+item.purpose}>{item.customer_name} · {item.purpose}</strong><span>{followupTime(item.due_at)}</span></div><button className="home-outline" onClick={()=>navigate('followups',item.id)}>跟进</button></li>)}</ul>:<div className="home-empty"><p>暂无待办跟进</p><button className="home-link" onClick={()=>navigate('chat')}>前往客户接待 <RightOutlined/></button></div>}
   </section>
   <section className="home-section" aria-labelledby="home-works-heading"><header><h2 id="home-works-heading">最近作品</h2><button className="home-link" onClick={()=>navigate('works')}>查看全部 <RightOutlined/></button></header>
    {worksError?<p className="home-empty" role="alert">作品暂时加载失败，请稍后重试。</p>:works===null?<p className="home-empty" role="status">正在加载作品…</p>:recent.length?<ul className="home-rows">{recent.map(work=><li key={work.id}>{work.content.images?.[0]?<img className="home-work-cover" src={'/api/knowledge/images/'+work.content.images[0].id} alt=""/>:<span className="home-work-cover home-work-empty"><FileTextOutlined/></span>}<div className="home-row-copy"><strong title={work.content.title}>{work.content.title}</strong><span>{work.brief.platform} · {time(work.updated_at)}</span></div><button className="home-outline" onClick={()=>navigate('works',work.id)}>打开</button></li>)}</ul>:<div className="home-empty"><p>暂无作品</p><button className="home-link" onClick={()=>navigate('create')}>创建第一份内容 <RightOutlined/></button></div>}
   </section>
  </div>
 </div>;
}
