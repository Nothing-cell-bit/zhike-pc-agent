import {useEffect,useState} from 'react';
import {Alert,Button,Tag} from 'antd';
import {api} from './api';

type Settings={base_url:string;model:string;key_configured:boolean;configured:boolean;source:string};
export function ImageModelSettings({onSaved}:{onSaved:()=>void}){
 const [saved,setSaved]=useState<Settings|null>(null),[base,setBase]=useState(''),[model,setModel]=useState(''),[key,setKey]=useState('');
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[warning,setWarning]=useState(''),[confirmReset,setConfirmReset]=useState(false);
 const apply=(value:Settings)=>{setSaved(value);setBase(value.base_url);setModel(value.model);setKey('');};
 useEffect(()=>{let active=true;api<Settings>('/admin/image-model').then(value=>{if(active)apply(value);}).catch(reason=>{if(active)setError(reason.message);});return()=>{active=false;};},[]);
 async function run(action:()=>Promise<void>){setBusy(true);setError('');setNotice('');setWarning('');try{await action();}catch(reason){setError(reason instanceof Error?reason.message:'操作失败，请稍后重试');}finally{setBusy(false);}}
 return <div className="image-model-settings"><div className="section-title"><h3>图片生成 API</h3><Tag color={saved?.configured?'green':'default'}>{saved?.configured?'已配置':'未配置'}</Tag></div>
 <p className="muted">填写自己的图片服务地址、模型名称和密钥。目前支持魔搭异步生图兼容接口（生成任务与任务查询），图片模型需支持所用功能的参考图。</p>
 {!saved&&!error&&<p>正在读取图片配置…</p>}
 {saved&&<form onSubmit={event=>{event.preventDefault();void run(async()=>{apply(await api<Settings>('/admin/image-model','PUT',{base_url:base.trim(),model:model.trim(),api_key:key}));setNotice('图片配置已保存，新建图片任务立即使用；已开始的任务沿用原配置。');onSaved();});}}>
 <label htmlFor="image-model-base">图片 API 基础地址</label><input id="image-model-base" className="date-input" style={{width:'100%',margin:'6px 0 14px'}} type="url" required value={base} onChange={event=>setBase(event.target.value)} placeholder="https://api-inference.modelscope.cn/v1" autoComplete="off" disabled={busy}/>
 <label htmlFor="image-model-name">图片模型名称</label><input id="image-model-name" className="date-input" style={{width:'100%',margin:'6px 0 14px'}} required maxLength={160} value={model} onChange={event=>setModel(event.target.value)} placeholder="Qwen/Qwen-Image-2.1-Turbo" disabled={busy}/>
 <label htmlFor="image-model-key">图片 API Key</label><input id="image-model-key" className="date-input" style={{width:'100%',margin:'6px 0'}} type="password" value={key} onChange={event=>setKey(event.target.value)} placeholder={saved.key_configured?'已保存密钥；同一地址留空可保留':'填写该图片服务的 API Key'} autoComplete="new-password" maxLength={8192} disabled={busy}/>
 <p className="muted">仅管理员可修改，密钥只存服务端私有目录，不会回显。更换地址须重新填写密钥。使用公网 HTTPS 基础地址，勿附加 /images/generations。</p>
 <div style={{display:'flex',gap:8,flexWrap:'wrap',marginBottom:12}}><Button type="primary" htmlType="submit" disabled={busy}>保存图片配置</Button><Button disabled={busy} onClick={()=>void run(async()=>{const result=await api('/admin/check-image-model','POST');if(result.ok===false)throw new Error(result.message||'连接未通过');if(result.ok===true)setNotice(result.message);else setWarning(result.message);})}>测试当前图片配置</Button></div>
 <p className="muted">当前来源：{saved.source==='custom'?'管理员自定义配置':'部署默认配置'}。测试只查询模型列表，不创建生图任务；实际生成才会使用图片额度。</p>
 {saved.source==='custom'&&<>{confirmReset?<div><span>恢复部署默认图片配置并删除自定义密钥？</span><Button disabled={busy} onClick={()=>void run(async()=>{apply(await api<Settings>('/admin/image-model/reset','POST'));setConfirmReset(false);setNotice('已恢复部署默认图片配置。');onSaved();})}>确认恢复默认图片配置</Button><Button onClick={()=>setConfirmReset(false)}>取消恢复</Button></div>:<Button disabled={busy} onClick={()=>setConfirmReset(true)}>恢复默认图片配置</Button>}</>}
 </form>}
 {busy&&<p role="status">正在处理图片配置…</p>}{error&&<Alert role="alert" type="error" message={error} showIcon/>}{warning&&<Alert role="status" type="warning" message={warning} showIcon/>}{notice&&<Alert role="status" type="success" message={notice} showIcon/>}
 </div>;
}
