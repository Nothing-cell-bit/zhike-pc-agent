import React,{useState} from 'react';
import {Alert,App,Button,Input,Modal,Select,Spin,Table,Tag} from 'antd';
import {api,Data,time} from './api';
import {useData} from './lifecycle';

type Snapshot={id:string;expected_owner:string|null;name:string};
const STATUS:Record<string,string>={waiting:'待分配',active:'接待中',closed:'已结束'};
const snapshot=(row:Data):Snapshot=>({id:row.id,expected_owner:row.owner_id||null,name:row.customer_name});
export function AdminConversationAllocation({onAccounts}:{onAccounts:()=>void}){
 const overview=useData('/admin/conversations',5000),[query,setQuery]=useState(''),[status,setStatus]=useState('all'),[owner,setOwner]=useState('all');
 const [selected,setSelected]=useState<Snapshot[]>([]),[dialog,setDialog]=useState<Snapshot[]|null>(null),[target,setTarget]=useState<string>(),[busy,setBusy]=useState(false),[error,setError]=useState('');const {message}=App.useApp();
 const data=overview.data,rows:Data[]=data?.conversations||[],staff:Data[]=data?.staff||[];
 const visible=rows.filter(row=>(status==='all'||row.status===status)&&(owner==='all'||(owner==='__unassigned__'?!row.owner_id:row.owner_id===owner))&&(row.customer_name+' '+row.owner_name+' '+row.stage).includes(query));
 const owners=Array.from(new Map(rows.filter(row=>row.owner_id).map(row=>[row.owner_id,row.owner_name])).entries());
 const open=(items:Snapshot[])=>{setDialog(items);setTarget(undefined);setError('');};
 const refresh=()=>{setSelected([]);void overview.refresh();};
 const assign=async()=>{
  if(!dialog||!target||busy)return;setBusy(true);setError('');
  try{const result=await api('/admin/conversations/assign','POST',{owner_id:target==='__unassigned__'?null:target,conversations:dialog.map(({id,expected_owner})=>({id,expected_owner}))});message.success(`已处理 ${result.count} 个对话`);setDialog(null);setSelected([]);await overview.refresh();}
  catch(reason){setError((reason as Error).message);void overview.refresh();}
  finally{setBusy(false);}
 };
 return <><div className="admin-page-heading"><h1>对话分配</h1><p>查看全站接待情况，按客服工作量分配与转交对话。</p></div>
  {!data?overview.error?<Alert type="error" message={overview.error} action={<Button onClick={refresh}>重试</Button>}/>:<Spin/>:<>
   <div className="admin-assignment-summary">{[['total','全部对话'],['unassigned','待分配'],['active','接待中'],['closed','已结束']].map(([key,label])=><div key={key}><span>{label}</span><strong>{data.summary[key]}</strong></div>)}</div>
   <section className="admin-card"><div className="admin-card-heading"><h2>客服工作量</h2><Button type="text" onClick={onAccounts}>管理客服账号</Button></div>
    {!staff.length?<Alert type="info" message="还没有客服账号，请先在管理员设置中创建。"/>:<div className="admin-staff-workload">{staff.map(item=><div key={item.id}><b>{item.display_name}</b>{!item.active&&<Tag>已停用</Tag>}<span>接待中 {item.active_count} · 待跟进 {item.pending_followups}</span></div>)}</div>}
   </section>
   <section className="admin-card"><div className="admin-assignment-toolbar"><Input aria-label="搜索对话" placeholder="搜索客户、负责人或阶段" value={query} onChange={event=>setQuery(event.target.value)}/>
    <Select aria-label="筛选接待状态" value={status} onChange={setStatus} options={[{value:'all',label:'全部状态'},...Object.entries(STATUS).map(([value,label])=>({value,label}))]}/>
    <Select aria-label="筛选负责人" value={owner} onChange={setOwner} options={[{value:'all',label:'全部负责人'},{value:'__unassigned__',label:'未分配'},...owners.map(([value,label])=>({value,label}))]}/>
    <Button disabled={busy} onClick={refresh}>刷新</Button><Button aria-label="批量分配" type="primary" disabled={!selected.length||busy} onClick={()=>open(selected)}>批量分配{selected.length?`（${selected.length}）`:''}</Button>
   </div>{overview.error&&<Alert type="warning" message={overview.error}/>}
   <Table<Data> rowKey="id" size="small" dataSource={visible} pagination={{pageSize:10}} scroll={{x:850}} rowSelection={{selectedRowKeys:selected.map(item=>item.id),preserveSelectedRowKeys:true,
    getCheckboxProps:row=>({disabled:row.status==='closed'||busy||selected.length>=50&&!selected.some(item=>item.id===row.id),'aria-label':'选择对话 '+row.customer_name}),
    onChange:keys=>{if(keys.length>50){message.info('一次最多分配50个对话');return;}setSelected(keys.map(key=>selected.find(item=>item.id===key)||snapshot(rows.find(row=>row.id===key)!)));},
   }} columns={[
    {title:'客户',dataIndex:'customer_name'},{title:'阶段',dataIndex:'stage'},{title:'负责人',render:(_,row)=><>{row.owner_name}{row.owner_id&&!row.owner_active&&<Tag>不可用</Tag>}</>},
    {title:'状态',dataIndex:'status',render:value=><Tag>{STATUS[value]||value}</Tag>},{title:'消息',dataIndex:'message_count'},{title:'更新时间',dataIndex:'updated_at',render:value=>time(value)},
    {title:'操作',render:(_,row)=><Button size="small" aria-label={'分配 '+row.customer_name} disabled={busy||row.status==='closed'} onClick={()=>open([snapshot(row)])}>分配</Button>},
   ]}/><p className="muted">一次最多分配50个对话，已结束的对话不参与分配。</p></section>
  </>}
  <Modal title={dialog?.length===1?'分配对话':'批量分配对话'} open={!!dialog} onCancel={()=>{if(!busy)setDialog(null);}} footer={<><Button disabled={busy} onClick={()=>setDialog(null)}>取消</Button><Button aria-label="确认分配" type="primary" loading={busy} disabled={!target} onClick={()=>void assign()}>确认分配</Button></>}>
   <p>已选 {dialog?.length||0} 个对话{dialog?.length===1?'：'+dialog[0].name:''}</p>
   {!!dialog&&dialog.length>1&&<details className="admin-assignment-selected"><summary>查看所选对话</summary><ul>{dialog.map(item=><li key={item.id}>{item.name}</li>)}</ul></details>}
   <p className="muted">转交时会同步未完成的跟进提醒，历史聊天和已完成记录保持原样。</p>
   <Select aria-label="分配给客服" value={target} onChange={setTarget} placeholder="选择负责人" disabled={busy} style={{width:'100%'}} options={[{value:'__unassigned__',label:'退回待分配'},...staff.map(item=>({value:item.id,label:`${item.display_name} · 接待中 ${item.active_count}${item.active?'':'（已停用）'}`,disabled:!item.active}))]}/>
   {error&&<Alert type="error" message={error} action={<Button size="small" onClick={()=>{setDialog(null);refresh();}}>重新选择</Button>}/>}
  </Modal>
 </>;
}
