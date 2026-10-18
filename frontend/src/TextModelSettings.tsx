import {useEffect,useState} from 'react';
import {Alert,Button,Tag} from 'antd';
import {api} from './api';

type Settings={base_url:string;model:string;key_configured:boolean;configured:boolean;source:string;disable_thinking?:boolean};
export function TextModelSettings({onSaved}:{onSaved:()=>void}){
 const [saved,setSaved]=useState<Settings|null>(null);
 const [base,setBase]=useState(''),[model,setModel]=useState(''),[key,setKey]=useState('');
 const [disableThinking,setDisableThinking]=useState(false);
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[confirmReset,setConfirmReset]=useState(false);
 const apply=(value:Settings)=>{setSaved(value);setBase(value.base_url);setModel(value.model);setKey('');setDisableThinking(value.disable_thinking||false);};
 useEffect(()=>{let active=true;api<Settings>('/admin/text-model').then(v=>{if(active)apply(v);}).catch(e=>{if(active)setError(e.message);});return()=>{active=false;};},[]);
 async function run(action:()=>Promise<void>){setBusy(true);setError('');setNotice('');try{await action();}catch(e){setError(e instanceof Error?e.message:'操作失败，请稍后重试');}finally{setBusy(false);}}
 return <div className="text-model-settings"><div className="section-title"><h3>语言模型</h3><Tag color={saved?.configured?'green':'default'}>{saved?.configured?'已配置':'未配置'}</Tag></div>
 <p className="muted">配置云端可访问的 OpenAI 兼容接口后，关掉电脑也能使用文本 AI。支持 Chat Completions 和 JSON 输出的模型。</p>
 {!saved&&!error&&<p>正在读取配置…</p>}
 {saved&&<form onSubmit={event=>{event.preventDefault();void run(async()=>{apply(await api<Settings>('/admin/text-model','PUT',{base_url:base.trim(),model:model.trim(),api_key:key,disable_thinking:disableThinking}));setNotice('保存成功，后续任务立即使用新配置；正在运行的请求使用原配置。');onSaved();});}}>
 <label htmlFor="text-model-base">API 基础地址</label><input id="text-model-base" className="date-input" style={{width:'100%',margin:'6px 0 14px'}} type="url" required value={base} onChange={e=>setBase(e.target.value)} placeholder="https://你的服务域名/v1" autoComplete="off" disabled={busy}/>
 <label htmlFor="text-model-name">模型名称</label><input id="text-model-name" className="date-input" style={{width:'100%',margin:'6px 0 14px'}} required maxLength={160} value={model} onChange={e=>setModel(e.target.value)} placeholder="服务商提供的模型 ID" disabled={busy}/>
 <label htmlFor="text-model-key">API Key</label><input id="text-model-key" className="date-input" style={{width:'100%',margin:'6px 0'}} type="password" value={key} onChange={e=>setKey(e.target.value)} placeholder={saved.key_configured?'已保存密钥；同一地址留空可保留':'首次配置请填写密钥'} autoComplete="new-password" maxLength={8192} disabled={busy}/>
 <p className="muted">仅管理员可修改。密钥只存服务端私有目录，不会回显。更换地址须重新填密钥。使用公网 HTTPS 基础地址，勿附加 /chat/completions。</p>
 <label style={{display:'block',marginBottom:12}}><input type="checkbox" checked={disableThinking} disabled={busy} onChange={e=>setDisableThinking(e.target.checked)}/> 关闭 Qwen 思考模式（仅用于支持此参数的 Qwen 服务）</label>
 <div style={{display:'flex',gap:8,flexWrap:'wrap',marginBottom:12}}><Button type="primary" htmlType="submit" disabled={busy}>保存模型配置</Button><Button disabled={busy} onClick={()=>void run(async()=>{const result=await api('/admin/check-model','POST');if(!result.ok)throw new Error(result.message||'连接未通过');setNotice(result.message||'模型连接正常');})}>测试当前已保存配置</Button></div>
 <p className="muted">当前来源：{saved.source==='custom'?'管理员自定义配置':'部署默认配置'}。测试会发送一次简短模型请求，可能消耗少量额度。</p>
 {saved.source==='custom'&&<>{confirmReset?<div><span>恢复部署默认配置并删除自定义密钥？</span><Button disabled={busy} onClick={()=>void run(async()=>{apply(await api<Settings>('/admin/text-model','DELETE'));setConfirmReset(false);setNotice('已恢复部署默认配置。');onSaved();})}>确认恢复默认</Button><Button onClick={()=>setConfirmReset(false)}>取消</Button></div>:<Button disabled={busy} onClick={()=>setConfirmReset(true)}>恢复部署默认配置</Button>}</>}
 </form>}
 {busy&&<p role="status">正在处理，请稍候…</p>}{error&&<Alert role="alert" type="error" message={error} showIcon/>}{notice&&<Alert role="status" type="success" message={notice} showIcon/>}
 </div>;
}
