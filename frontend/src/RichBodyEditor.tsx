import React,{createContext,forwardRef,useCallback,useContext,useEffect,useImperativeHandle,useRef,useState} from 'react';
import {EditorContent,useEditor} from '@tiptap/react';
import {Editor,JSONContent,Mark,Node} from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import {Markdown} from '@tiptap/markdown';
import {AutoComplete,Button,Input,InputNumber,Select,Tooltip} from 'antd';
import {BoldOutlined,ItalicOutlined,UnorderedListOutlined,OrderedListOutlined,UndoOutlined,RedoOutlined,PictureOutlined} from '@ant-design/icons';
import {Data} from './api';
import {RichTextMap,TextField,textStyle,validFont} from './richText';
import {workImageUrl} from './workImages';

const ProductImage=Node.create({
 name:'productImage',group:'block',atom:true,draggable:true,
 addAttributes(){return {id:{default:''},caption:{default:''}};},
 parseHTML(){return [{tag:'figure[data-product-id]',getAttrs:(element)=>({id:(element as HTMLElement).dataset.productId,caption:(element as HTMLElement).querySelector('figcaption')?.textContent||''})}];},
 renderHTML({node}){return ['figure',{'data-product-id':node.attrs.id,class:'writer-product-image',contenteditable:'false'},
  ['img',{src:workImageUrl(node.attrs.id),alt:node.attrs.caption||'配图'}],['figcaption',{},node.attrs.caption]];},
 renderMarkdown(){return '';},
});
const TextStyle=Mark.create({
 name:'textStyle',addAttributes(){return {fontFamily:{default:null},fontSize:{default:null}};},
 parseHTML(){return [{tag:'span[style]',getAttrs:element=>({fontFamily:(element as HTMLElement).style.fontFamily||null,fontSize:(element as HTMLElement).style.fontSize||null})}];},
 renderHTML({mark}){const style=textStyle(mark.attrs);return ['span',{style:[style.fontFamily?'font-family:'+style.fontFamily:'',style.fontSize?'font-size:'+style.fontSize:''].filter(Boolean).join(';')},0];},
 renderMarkdown:(node,helpers)=>helpers.renderChildren(node),
});
export const bodyExtensions=[StarterKit.configure({heading:{levels:[1,2,3]},underline:false,link:{openOnClick:false}}),Markdown,TextStyle,ProductImage];
const countBlocks=(text:string)=>text.trim()?text.trim().split(/\n\s*\n/).length:0;
const serialize=(editor:Editor,nodes:JSONContent[])=>editor.markdown!.serialize({type:'doc',content:nodes});

export function createBodyDocument(editor:Editor,body:string,images:Data[]):JSONContent{
 const parsed=editor.markdown!.parse(body),nodes=parsed.content||[];
 const output:JSONContent[]=[];const placed=new Set<string>();
 const add=(slot:number)=>{for(const image of images){
  const position=image.after_block??Number(/第(\d+)/.exec(image.position||'')?.[1]||images.indexOf(image)+1);
  if(!placed.has(image.id)&&position<=slot){placed.add(image.id);output.push({type:'productImage',attrs:{id:image.id,caption:image.caption||image.description||image.name||''}});}
 }};
 add(0);
 nodes.forEach((node,index)=>{output.push(node);add(countBlocks(serialize(editor,nodes.slice(0,index+1))));});
 add(Number.MAX_SAFE_INTEGER);
 return {type:'doc',content:output.length?output:[{type:'paragraph'}]};
}

export function readBodyDocument(editor:Editor,choices:Data[]){
 const text:JSONContent[]=[],images:Data[]=[];const allowed=new Map(choices.map(image=>[image.id,image]));
 for(const node of editor.getJSON().content||[]){
  if(node.type==='productImage'){
   const original=allowed.get(node.attrs?.id);
   if(original&&images.length<6&&!images.some(image=>image.id===original.id))images.push({...original,after_block:countBlocks(serialize(editor,text))});
  }else text.push(node);
 }
 return {body:serialize(editor,text).trim(),images};
}

export type RichBodyHandle={insertImage:(image:Data)=>void;removeImage:(id:string)=>void};
type FieldContext={activate:(editor:Editor,field:TextField)=>void;notify:()=>void;toolbarAction:React.MutableRefObject<boolean>;richText:RichTextMap;disabled:boolean;change:(value:Data)=>void};
const Fields=createContext<FieldContext|null>(null);
const emptyText=(value:string):JSONContent=>({type:'doc',content:value.split('\n').map(text=>({type:'paragraph',content:text?[{type:'text',text}]:undefined}))});
const startSelection=(editor:Editor)=>editor.commands.setTextSelection(1);
export function RichTextField({field,label,value,className,placeholder}:{field:Exclude<TextField,'body'>;label:string;value:string;className:string;placeholder?:string}){
 const context=useContext(Fields)!;const current=useRef({context,value});current.current={context,value};const ready=useRef(false);
 const document=()=>{const saved=current.current.context.richText[field];return saved?.source===current.current.value?saved.doc:emptyText(current.current.value);};
 const editor=useEditor({extensions:bodyExtensions.filter(extension=>extension.name!=='productImage'),content:'',editable:!context.disabled,
  editorProps:{attributes:{role:'textbox','aria-label':label,'aria-multiline':'true','data-placeholder':placeholder||''},handleScrollToSelection:()=>current.current.context.toolbarAction.current},
  onCreate:({editor})=>{editor.commands.setContent(document(),{emitUpdate:false});startSelection(editor);ready.current=true;},
  onFocus:({editor})=>current.current.context.activate(editor,field),
  onSelectionUpdate:()=>current.current.context.notify(),onTransaction:()=>current.current.context.notify(),
  onUpdate:({editor})=>{if(!ready.current)return;const source=editor.getText({blockSeparator:'\n'});const ctx=current.current.context;ctx.change({[field]:source,rich_text:{...ctx.richText,[field]:{source,doc:editor.getJSON()}}});},
 });
 useEffect(()=>{editor?.setEditable(!context.disabled,false);},[editor,context.disabled]);
 useEffect(()=>{
  if(!editor||!ready.current)return;const target=document();
  if(JSON.stringify(editor.getJSON())!==JSON.stringify(target))editor.commands.setContent(target,{emitUpdate:false});
 },[editor,value,context.richText[field]]);
 return <EditorContent className={'writer-text-field '+className} editor={editor}/>;
}

type Props={body:string;images:Data[];choices:Data[];richText?:RichTextMap;disabled:boolean;onChange:(value:Data)=>void;onImages:()=>void;children?:React.ReactNode;footer?:React.ReactNode};
const fieldLabels:Record<TextField,string>={title:'标题',intro:'导语',body:'正文',cta:'结尾标语'};
export const RichBodyEditor=forwardRef<RichBodyHandle,Props>(function RichBodyEditor({body,images,choices,richText={},disabled,onChange,onImages,children,footer},ref){
 const current=useRef({body,images,choices,richText,onChange});current.current={body,images,choices,richText,onChange};
 const ready=useRef(false),toolbarAction=useRef(false);
 const [active,setActive]=useState<{editor:Editor;field:TextField}|null>(null),[,updateToolbar]=useState(0);
 const activate=useCallback((editor:Editor,field:TextField)=>setActive(current=>current?.editor===editor?current:{editor,field}),[]);
 const notify=useCallback(()=>updateToolbar(value=>value+1),[]);
 const runToolbarAction=(run:()=>void)=>{if(!active||disabled)return;toolbarAction.current=true;try{run();}finally{toolbarAction.current=false;}};
 const bodyDocument=(editor:Editor)=>{const saved=current.current.richText.body;return saved?.source===current.current.body?saved.doc:createBodyDocument(editor,current.current.body,current.current.images);};
 const editor=useEditor({extensions:bodyExtensions,content:'',editable:!disabled,
  editorProps:{attributes:{role:'textbox','aria-label':'正文','aria-multiline':'true','data-placeholder':'从这里开始写正文…'},handleScrollToSelection:()=>toolbarAction.current},
  onCreate:({editor})=>{editor.commands.setContent(bodyDocument(editor),{emitUpdate:false});startSelection(editor);ready.current=true;},
  onFocus:({editor})=>activate(editor,'body'),onSelectionUpdate:notify,onTransaction:notify,
  onUpdate:({editor})=>{if(ready.current){const value=readBodyDocument(editor,current.current.choices);current.current.onChange({...value,rich_text:{...current.current.richText,body:{source:value.body,doc:editor.getJSON()}}});}},
 });
 useEffect(()=>{editor?.setEditable(!disabled,false);},[editor,disabled]);
 useEffect(()=>{
  if(!editor||!ready.current)return;
  const saved=richText.body;
  if(saved?.source===body){
   const canonical=readBodyDocument(editor,choices);const positions=(list:Data[])=>JSON.stringify(list.map(image=>[image.id,image.after_block??0]));
   if(JSON.stringify(editor.getJSON())!==JSON.stringify(saved.doc))editor.commands.setContent(saved.doc,{emitUpdate:false});
   if(positions(canonical.images)!==positions(images))editor.commands.setContent(createBodyDocument(editor,body,images),{emitUpdate:false});
   return;
  }
  const existing=readBodyDocument(editor,choices),target=createBodyDocument(editor,body,images);
  if(existing.body!==body||JSON.stringify(existing.images.map(image=>image.id))!==JSON.stringify(images.map(image=>image.id)))editor.commands.setContent(target,{emitUpdate:false});
 },[editor,body,images,choices,richText.body]);
 useImperativeHandle(ref,()=>({
  insertImage(image){if(editor&&!disabled){activate(editor,'body');toolbarAction.current=true;try{editor.chain().insertContent({type:'productImage',attrs:{id:image.id,caption:image.caption||image.description||image.name||''}}).run();}finally{toolbarAction.current=false;}}},
  removeImage(id){if(!editor||disabled)return;const ranges:{from:number;to:number}[]=[];editor.state.doc.descendants((node,pos)=>{if(node.type.name==='productImage'&&node.attrs.id===id)ranges.push({from:pos,to:pos+node.nodeSize});});for(const range of ranges.reverse())editor.commands.deleteRange(range);},
 }),[editor,disabled,activate]);
 const target=active?.editor,chain=()=>target?.chain().focus(null,{scrollIntoView:false});
 const control=(name:string,icon:React.ReactNode,run:()=>void,pressed?:boolean)=><Tooltip title={name}><Button aria-label={name} aria-pressed={pressed} type="text" disabled={disabled||!target} icon={icon} onMouseDown={event=>event.preventDefault()} onClick={()=>runToolbarAction(run)}/></Tooltip>;
 const [font,setFont]=useState(''),[size,setSize]=useState<number|null>(null),[fontError,setFontError]=useState('');
 const selectedStyle=target?.getAttributes('textStyle'),selectedFont=selectedStyle?.fontFamily||'',selectedSize=selectedStyle?.fontSize||'';
 useEffect(()=>{setFont(selectedFont);setSize(selectedSize?parseInt(selectedSize):active?.field==='title'?32:active?.field==='body'?16:15);setFontError('');},[active,selectedFont,selectedSize]);
 const applyFont=(value:string)=>{
  const clean=value.trim();if(clean&&!validFont(clean)){setFontError('字体名只能填写文字、数字、空格和逗号');return;}setFontError('');
  runToolbarAction(()=>{chain()?.setMark('textStyle',{fontFamily:clean||null}).run();});
 };
 const applySize=()=>{if(size===null||size<10||size>96)return;runToolbarAction(()=>{chain()?.setMark('textStyle',{fontSize:size+'px'}).run();});};
 const context:FieldContext={activate,notify,toolbarAction,richText,disabled,change:onChange};
 return <Fields.Provider value={context}>
  <div className="writer-formatbar" role="toolbar" aria-label="文稿格式">
   <Select aria-label="段落样式" value={target?.isActive('heading',{level:2})?'h2':target?.isActive('heading',{level:3})?'h3':'p'} disabled={disabled||!target} onChange={value=>runToolbarAction(()=>{value==='p'?chain()?.setParagraph().run():chain()?.toggleHeading({level:value==='h2'?2:3}).run();})} options={[{value:'p',label:'正文'},{value:'h2',label:'二级标题'},{value:'h3',label:'三级标题'}]}/>
   <AutoComplete className="writer-font-input" value={font} disabled={disabled||!target} onChange={setFont} onSelect={value=>{setFont(value);applyFont(value);}} options={['Microsoft YaHei','宋体','楷体','Arial','Times New Roman'].map(value=>({value}))}>
    <Input aria-label="字体" placeholder="输入字体名" maxLength={80} onBlur={()=>applyFont(font)} onPressEnter={event=>event.currentTarget.blur()}/>
   </AutoComplete>
   <InputNumber aria-label="字号" className="writer-font-size" min={10} max={96} value={size} disabled={disabled||!target} onChange={value=>setSize(value)} onBlur={applySize} onPressEnter={event=>event.currentTarget.blur()}/><span className="writer-font-unit">px</span>
   <span className="writer-tool-divider"/>
   {control('加粗',<BoldOutlined/>,()=>{chain()?.toggleBold().run();},!!target?.isActive('bold'))}
   {control('斜体',<ItalicOutlined/>,()=>{chain()?.toggleItalic().run();},!!target?.isActive('italic'))}
   {control('无序列表',<UnorderedListOutlined/>,()=>{chain()?.toggleBulletList().run();},!!target?.isActive('bulletList'))}
   {control('有序列表',<OrderedListOutlined/>,()=>{chain()?.toggleOrderedList().run();},!!target?.isActive('orderedList'))}
   <span className="writer-tool-divider"/>
   <Tooltip title="插入配图 / 本地上传"><Button aria-label="插入配图" type="text" disabled={disabled} icon={<PictureOutlined/>} onMouseDown={event=>event.preventDefault()} onClick={onImages}/></Tooltip>
   <span className="writer-format-spacer"/><span className="writer-format-target">{active?fieldLabels[active.field]:'先选中文字'}</span>
   {control('撤销',<UndoOutlined/>,()=>{chain()?.undo().run();})}
   {control('重做',<RedoOutlined/>,()=>{chain()?.redo().run();})}
   {fontError&&<span role="alert">{fontError}</span>}
  </div>
  {children}
  <EditorContent className="writer-rich-body writer-text-field" editor={editor}/>
  {footer}
 </Fields.Provider>;
});
