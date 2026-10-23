import React,{useState} from 'react';
import {Alert,Button,Checkbox,Form,Input,InputNumber,Modal,Select,Table,Tag} from 'antd';
import {api,Data} from './api';
import {useData} from './lifecycle';

export function PriceRuleSettings(){
 const rules=useData('/admin/price-rules'),options=useData('/admin/price-options');
 const [form]=Form.useForm();
 const [open,setOpen]=useState(false),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const execute=async(action:()=>Promise<unknown>)=>{if(busy)return;setError('');setBusy(true);try{await action();await rules.refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
 return <section className="panel"><div className="section-title"><h2>门店报价规则</h2><Button onClick={()=>setOpen(true)}>新增规则</Button></div>
 <p className="muted">录入获授权的配置与价格依据，由另一位管理员复核后用于报价。未配置时只提供参考信息。</p>
 {(error||rules.error||options.error)&&<Alert type="error" message={error||rules.error||options.error}/>}
 <Table size="small" rowKey="id" dataSource={rules.data||[]} pagination={{pageSize:5}} columns={[
  {title:'配置',render:(_:unknown,row:Data)=><span>{(options.data||[]).find((o:Data)=>o.id===row.variant_id)?.variant||row.variant_id}</span>},
  {title:'类型',render:(_:unknown,row:Data)=>row.payload?.level||'L1'},
  {title:'含税单价',render:(_:unknown,row:Data)=>'¥'+(row.payload?.unit_minor/100).toLocaleString('zh-CN')},
  {title:'状态',render:(_:unknown,row:Data)=><Tag>{row.status==='approved'?'已复核':row.status==='revoked'?'已撤销':'待复核'}</Tag>},
  {title:'操作',render:(_:unknown,row:Data)=>row.status==='draft'?<Button size="small" disabled={busy} onClick={()=>void execute(()=>api('/admin/price-rules/'+row.id+'/approve','POST'))}>复核通过</Button>:row.status==='approved'?<Button size="small" disabled={busy} onClick={()=>void execute(()=>api('/admin/price-rules/'+row.id+'/revoke','POST'))}>撤销</Button>:null},
 ]}/>
 <Modal open={open} title="录入报价规则" footer={null} onCancel={()=>setOpen(false)} width={760}><p className="muted">这是门店内部录入格式，实际金额、优惠和授权须有对应依据。</p>{error&&<Alert type="error" message={error}/>}<Form form={form} layout="vertical" onFinish={values=>void execute(async()=>{
  const option=(options.data||[]).find((o:Data)=>o.id===values.variant_id);
  if(!option)throw new Error('请重新选择有效产品配置');
  const discounts=(values.discounts||[]).map((item:Data,index:number)=>({id:'discount-'+(index+1),kind:item.kind,...(item.qualification?{qualification:item.qualification.trim()}:{}),...(item.kind==='fixed'?{scope:item.scope,amount_minor:Math.round(item.value*100)}:{basis:item.basis,basis_points:Math.round(item.value*100),rounding:'half_up',...(item.cap!=null?{cap_minor:Math.round(item.cap*100)}:{})})}));
  const components=(values.components||[]).map((item:Data)=>({name:item.name,sku_ref:item.sku_ref,quantity:item.quantity,unit_minor:Math.round(item.price*100)}));
  await api('/admin/price-rules','POST',{product_id:option.product_id,variant_id:values.variant_id,payload:{level:values.level,sku_ref:values.sku_ref,unit_minor:Math.round(values.price*100),fees_minor:Math.round((values.fees||0)*100),currency:'CNY',tax_included:true,max_quantity:values.quantity||1,source_id:values.source,approval_id:values.approval,valid_from:new Date(values.start+'+08:00').toISOString(),valid_until:new Date(values.end+'+08:00').toISOString(),qualifications_required:values.qualification?[values.qualification.trim()]:[],discounts,stacking_confirmed:values.stacking_confirmed===true,...(values.level==='L3'?{components}:{})}});setOpen(false);form.resetFields();
 })} initialValues={{level:'L1',fees:0,quantity:1}}>
 <Form.Item name="variant_id" label="产品与配置" rules={[{required:true}]}><Select showSearch optionFilterProp="label" options={(options.data||[]).map((o:Data)=>({value:o.id,label:o.name+' · '+o.variant}))}/></Form.Item>
 <Form.Item name="sku_ref" label="已核实销售 SKU 或商家配置编号" rules={[{required:true}]}><Input/></Form.Item>
 <Form.Item name="level" label="报价类型"><Select options={[['L1','单机标准'],['L2','资格优惠'],['L3','套装方案'],['L4','审批专项']].map(([value,label])=>({value,label}))}/></Form.Item>
 <div className="form-two"><Form.Item name="price" label="含税单价（元）" rules={[{required:true}]}><InputNumber min={0.01} precision={2}/></Form.Item><Form.Item name="fees" label="额外费用（元）"><InputNumber min={0} precision={2}/></Form.Item></div>
 <Form.Item name="quantity" label="授权最大数量"><InputNumber min={1} precision={0}/></Form.Item>
 <Form.Item name="qualification" label="所需资格代码（可选）"><Input placeholder="需管理员核验对应客户资格后才适用"/></Form.Item>
 <h3>优惠算法</h3><p className="muted">减免比例填写优惠百分比，例如减免 10% 填 10。多项优惠须确认顺序与叠加，按列表顺序计算。</p>
 <Form.List name="discounts">{(fields,{add,remove})=><>{fields.map(field=><fieldset key={field.key}><legend>优惠 {field.name+1}</legend>
  <Form.Item name={[field.name,'kind']} label="优惠方式" rules={[{required:true}]}><Select options={[{value:'fixed',label:'固定金额减免'},{value:'rate',label:'比例减免'}]}/></Form.Item>
  <Form.Item noStyle shouldUpdate>{()=>form.getFieldValue(['discounts',field.name,'kind'])==='rate'?<>
   <Form.Item name={[field.name,'value']} label="减免比例（%）" rules={[{required:true}]}><InputNumber min={0} max={100} precision={2}/></Form.Item>
   <Form.Item name={[field.name,'basis']} label="比例计算基数" rules={[{required:true}]}><Select options={[{value:'base',label:'原商品总价（不含附加费）'},{value:'remaining',label:'前序减免后的应付金额（含附加费）'}]}/></Form.Item>
   <Form.Item name={[field.name,'cap']} label="减免上限（元，可选）"><InputNumber min={0} precision={2}/></Form.Item>
  </>:<>
   <Form.Item name={[field.name,'value']} label="减免金额（元）" rules={[{required:true}]}><InputNumber min={0} precision={2}/></Form.Item>
   <Form.Item name={[field.name,'scope']} label="减免口径" rules={[{required:true}]}><Select options={[{value:'unit',label:'每台 / 每套'},{value:'quote',label:'整单一次'}]}/></Form.Item>
  </>}</Form.Item>
  <Form.Item name={[field.name,'qualification']} label="本项优惠资格代码（可选）"><Input/></Form.Item>
  <Button onClick={()=>remove(field.name)}>移除此优惠</Button>
 </fieldset>)}<Button onClick={()=>add({kind:'fixed',scope:'unit',basis:'base',value:0})}>添加优惠</Button></>}</Form.List>
 <Form.Item name="stacking_confirmed" valuePropName="checked"><Checkbox>依据已确认上述优惠可以按此顺序叠加</Checkbox></Form.Item>
 <h3>套装商品与服务</h3><p className="muted">L3 必填：数量按每套组成填写，明细合计必须等于上方含税单价；赠品可填零元。</p>
 <Form.List name="components">{(fields,{add,remove})=><>{fields.map(field=><fieldset key={field.key}><legend>组件 {field.name+1}</legend>
  <Form.Item name={[field.name,'name']} label="商品或服务名称" rules={[{required:true}]}><Input maxLength={100}/></Form.Item>
  <Form.Item name={[field.name,'sku_ref']} label="组件 SKU 或服务编号" rules={[{required:true}]}><Input maxLength={100}/></Form.Item>
  <div className="form-two"><Form.Item name={[field.name,'quantity']} label="每套数量" rules={[{required:true}]}><InputNumber min={1} max={1000} precision={0}/></Form.Item><Form.Item name={[field.name,'price']} label="组件单价（元）" rules={[{required:true}]}><InputNumber min={0} precision={2}/></Form.Item></div>
  <Button onClick={()=>remove(field.name)}>移除此组件</Button>
 </fieldset>)}<Button onClick={()=>add({quantity:1,price:0})}>添加商品或服务</Button></>}</Form.List>
 <Form.Item name="source" label="授权价格来源或凭据编号" rules={[{required:true}]}><Input/></Form.Item>
 <Form.Item name="approval" label="业务批准记录编号" rules={[{required:true}]}><Input/></Form.Item>
 <Form.Item name="start" label="生效时间（北京时间）" rules={[{required:true}]}><input className="date-input" type="datetime-local"/></Form.Item>
 <Form.Item name="end" label="失效时间（北京时间）" rules={[{required:true}]}><input className="date-input" type="datetime-local"/></Form.Item>
 <Button htmlType="submit" type="primary" loading={busy}>保存为待复核规则</Button>
 </Form></Modal></section>;
}
