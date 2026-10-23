import React from 'react';

type Block={text:string}|{headers:string[];rows:string[][]};
const cells=(line:string)=>line.trim().replace(/^\|/,'').replace(/\|$/,'').split('|').map(x=>x.trim());
const value=(text:string)=>text.replace(/<br\s*\/?\s*>/gi,'\n').replace(/（资料原文）/g,'').replace(/(^|\n)\s*\*/g,'$1');
function blocks(text:string):Block[]{
 const lines=text.replace(/\r\n/g,'\n').split('\n'),result:Block[]=[];let plain:string[]=[];
 const flush=()=>{if(plain.length)result.push({text:plain.join('\n')});plain=[];};
 for(let i=0;i<lines.length;i++){
  if(lines[i].trim().startsWith('|')&&/^\s*\|?\s*:?-{3,}/.test(lines[i+1]||'')){
   const headers=cells(lines[i]);if(!cells(lines[i+1]).every(x=>/^:?-{3,}:?$/.test(x))){plain.push(lines[i]);continue;}
   const rows:string[][]=[];let end=i+2;
   while(end<lines.length&&lines[end].trim().startsWith('|')){const row=cells(lines[end]);if(row.length!==headers.length)break;rows.push(row);end++;}
   if(rows.length){flush();result.push({headers,rows});i=end-1;continue;}
  }
  plain.push(lines[i]);
 }
 flush();return result;
}

export function ChatMessageContent({text,customer=false}:{text?:string|null;customer?:boolean}){
 const source=text??'';
 if(customer)return <div className="chat-message-text">{source}</div>;
 return <div className="chat-message-content">{blocks(source).map((block,index)=>'text' in block?
  <div className="chat-message-text" key={index}>{block.text}</div>:
  <details className="chat-specifications" key={index}><summary>查看产品参数</summary>
   {block.rows.map((row,r)=><section className="chat-specification" key={r}><h4>{value(row[0])}</h4>
    <dl>{row.slice(1).map((cell,c)=><div key={c}><dt>{value(block.headers[c+1])}</dt><dd>{value(cell)}</dd></div>)}</dl>
   </section>)}
  </details>)}</div>;
}
