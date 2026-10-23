import React,{useEffect,useRef,useState} from 'react';
import {Alert,Button} from 'antd';
import {EditOutlined} from '@ant-design/icons';
import {api,Data} from './api';

type Props={conversationId:string;productId:string;disabled:boolean;onImport:(brief:Data)=>void};
export function ChatMarketingButton({conversationId,productId,disabled,onImport}:Props){
 const [loading,setLoading]=useState(false),[error,setError]=useState('');
 const mounted=useRef(true),inFlight=useRef(false);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
 const transfer=async()=>{
  if(disabled||inFlight.current)return;inFlight.current=true;setLoading(true);setError('');
  try{
   const brief=await api('/conversations/'+encodeURIComponent(conversationId)+'/marketing-brief'+(productId?'?product_id='+encodeURIComponent(productId):''));
   if(mounted.current)onImport(brief);
  }catch(reason){if(mounted.current)setError((reason as Error).message);}
  finally{inFlight.current=false;if(mounted.current)setLoading(false);}
 };
 return <><Button block type="primary" ghost icon={<EditOutlined/>} loading={loading} disabled={disabled} onClick={()=>void transfer()}>转为营销创作任务</Button>{error&&<Alert type="error" message={error}/>}</>;
}
