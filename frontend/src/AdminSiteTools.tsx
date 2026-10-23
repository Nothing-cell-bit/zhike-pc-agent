import React,{useEffect,useRef,useState} from 'react';
import {Alert,App,Button,Descriptions,Spin,Table,Tag} from 'antd';
import {api,Data,statuses,time} from './api';
import {useData} from './lifecycle';
import {TextModelSettings} from './TextModelSettings';
import {ImageModelSettings} from './ImageModelSettings';

function SettingsJob({id,onCompleted}:{id:string;onCompleted:()=>void}){
 const job=useData('/jobs/'+id,2000),reported=useRef('');
 useEffect(()=>{if(job.data?.status==='completed'&&reported.current!==id){reported.current=id;onCompleted();}},[job.data?.status,id,onCompleted]);
 return job.error?<Alert type="error" message={job.error}/>:job.data?<div className="admin-settings-job"><Tag>{statuses[job.data.status]||job.data.status}</Tag><span>{job.data.step}</span>{job.data.error&&<Alert type="warning" message={job.data.error}/>}</div>:<Spin/>;
}

export function SiteAiSettings(){
 const status=useData('/admin/status');
 return <div className="admin-settings-stack"><section className="admin-card"><h2>AI 配置</h2><TextModelSettings onSaved={()=>void status.refresh()}/></section>
  <section className="admin-card"><h2>图片生成服务</h2><ImageModelSettings onSaved={()=>void status.refresh()}/>{status.data?.image?.last_error&&<Alert type="warning" message={status.data.image.last_error}/>}</section>
 </div>;
}

export function SiteKnowledgeSettings(){
 const status=useData('/admin/status'),[busy,setBusy]=useState(false),[error,setError]=useState(''),[job,setJob]=useState('');
 const rebuild=async()=>{if(busy)return;setBusy(true);setError('');try{const result=await api('/admin/knowledge/reindex','POST');setJob(result.job_id);}catch(reason){setError((reason as Error).message);}finally{setBusy(false);}};
 const source=status.data?.marketing_knowledge;
 return <section className="admin-card"><h2>产品知识库</h2>{status.error?<Alert type="error" message={status.error}/>:!status.data?<Spin/>:<>
  <p>营销检索：{source?.provider==='ima_first'?'ima 优先，失败时使用本地资料':source?.provider==='ima'?'仅使用 ima':'本地资料'}</p>
  {source?.configured&&<p className="muted">{source.library_name} · {source.connected?'最近检索成功':'等待检索或上次调用失败'}</p>}
  <Descriptions column={2} size="small" items={['version','documents','products','images','checked_files'].map((key,index)=>({key,label:['版本','文档','产品','图片','校验文件'][index],children:status.data.knowledge[key]??'—'}))}/>
  <p className="muted">校验现有知识包并重建索引，历史作品保留原来源。</p><Button loading={busy} disabled={!!job} onClick={()=>void rebuild()}>校验并重建索引</Button>
 </>}{error&&<Alert type="error" message={error}/>} {job&&<><SettingsJob id={job} onCompleted={()=>void status.refresh()}/><Button type="text" onClick={()=>setJob('')}>收起任务</Button></>}</section>;
}

const JOB_NAMES:Record<string,string>={generate:'内容生成',analysis:'需求分析',suggest:'回复建议',pricing:'报价方案',verify:'内容核验',repair:'内容修订',import:'知识库更新',image:'图片背景',poster:'AI海报',moments_gallery:'朋友圈配图'};
const AUDIT_NAMES:Record<string,string>={assign_conversation:'分配对话',update_text_model:'更新AI配置',update_store:'保存网站设置',create_staff:'创建员工',edit_staff:'修改员工',backup:'创建备份',restore_drill:'恢复演练',login:'登录'};
export function SiteOperations(){
 const status=useData('/admin/status',15000),jobs=useData('/jobs',5000),audit=useData('/admin/audit');
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[job,setJob]=useState('');const {message}=App.useApp();
 const run=async(action:()=>Promise<void>)=>{if(busy)return;setBusy(true);setError('');setNotice('');try{await action();}catch(reason){setError((reason as Error).message);}finally{setBusy(false);}};
 return <div className="admin-settings-stack"><section className="admin-card"><h2>备份与恢复</h2><p className="muted">恢复演练在独立临时库进行，不覆盖当前网站数据。</p><div className="admin-inline-actions">
  <Button loading={busy} onClick={()=>void run(async()=>{const result=await api('/admin/backup','POST');setNotice('备份已保存：'+result.filename);await status.refresh();})}>立即备份</Button>
  <Button disabled={busy} onClick={()=>void run(async()=>{const result=await api('/admin/backup/drill','POST');setNotice('恢复演练完成，完整性检查：'+result.integrity);await status.refresh();})}>运行恢复演练</Button>
 </div><p className="muted">最近备份：{status.data?.backups?.slice(-1)[0]||'暂无手动备份'}</p>{notice&&<Alert type="success" message={notice}/>}</section>
 <section className="admin-card"><h2>运行任务</h2>{(error||jobs.error)&&<Alert type="error" message={error||jobs.error}/>}<Table<Data> size="small" rowKey="id" dataSource={jobs.data||[]} loading={!jobs.data&&!jobs.error} pagination={{pageSize:8}} scroll={{x:650}} columns={[
  {title:'任务',dataIndex:'kind',render:kind=>JOB_NAMES[kind]||kind},{title:'状态',dataIndex:'status',render:value=><Tag>{statuses[value]||value}</Tag>},{title:'进度',dataIndex:'step'},{title:'时间',dataIndex:'created_at',render:value=>time(value)},
  {title:'操作',render:(_,row)=>['failed','waiting_remote','cancelled'].includes(row.status)&&row.kind!=='import'?<Button size="small" disabled={busy} onClick={()=>void run(async()=>{const result=await api('/jobs/'+row.id+'/retry','POST');setJob(result.job_id);message.success('已提交重试');await jobs.refresh();})}>重试</Button>:null},
 ]}/>{job&&<SettingsJob id={job} onCompleted={()=>void jobs.refresh()}/>}</section>
 <section className="admin-card"><h2>操作记录</h2>{audit.error&&<Alert type="error" message={audit.error}/>}<Table<Data> size="small" rowKey="id" dataSource={audit.data||[]} pagination={{pageSize:8}} columns={[{title:'动作',dataIndex:'action',render:value=>AUDIT_NAMES[value]||value},{title:'时间',dataIndex:'created_at',render:value=>time(value)}]}/></section>
 </div>;
}
