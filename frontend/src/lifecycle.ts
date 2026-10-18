import {useCallback, useEffect, useRef, useState} from 'react';
import {api, Data} from './api';

export function useData(path:string, interval=0) {
  const [state,setState]=useState<{path:string;data:any;error:string}>({path,data:null,error:''});
  const current=useRef(path),serial=useRef(0),mounted=useRef(true);
  current.current=path;
  const refresh=useCallback(async()=>{
    const request=++serial.current;
    try {
      const data=await api(path);
      if(mounted.current&&current.current===path&&request===serial.current)setState({path,data,error:''});
      return data;
    } catch(error) {
      if(mounted.current&&current.current===path&&request===serial.current)setState(old=>({path,data:old.path===path?old.data:null,error:(error as Error).message}));
    }
  },[path]);
  useEffect(()=>{
    mounted.current=true;
    void refresh();
    const timer=interval?setInterval(refresh,interval):undefined;
    return()=>{mounted.current=false;++serial.current;clearInterval(timer);};
  },[refresh,interval]);
  return {data:state.path===path?state.data:null,error:state.path===path?state.error:'',refresh};
}

export function watchJob(id:string,onUpdate:(job:Data)=>void,onDone?:(job:Data)=>void) {
  let stopped=false,polling=false,timer:ReturnType<typeof setTimeout>|undefined;
  const stream=new EventSource('/api/jobs/'+encodeURIComponent(id)+'/events');
  const stop=()=>{stopped=true;stream.close();clearTimeout(timer);};
  const receive=(job:Data)=>{
    if(stopped)return;
    onUpdate(job);
    if(!['queued','running'].includes(job.status)){
      stop();
      if(job.status==='completed')onDone?.(job);
    }
  };
  const poll=async()=>{
    if(stopped)return;
    try{receive(await api('/jobs/'+encodeURIComponent(id)));}
    catch{/* Temporary disconnect: retain saved job ID and resume reads. */}
    if(!stopped)timer=setTimeout(poll,1500);
  };
  stream.onmessage=e=>{
    try{receive(JSON.parse(e.data));}
    catch{stream.onerror?.(new Event('error'));}
  };
  stream.onerror=()=>{
    stream.close();
    if(!stopped&&!polling){polling=true;void poll();}
  };
  return stop;
}
