// @vitest-environment jsdom
import {Editor} from '@tiptap/core';
import {afterEach,expect,it} from 'vitest';
import React from 'react';
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {vi} from 'vitest';
import {bodyExtensions,createBodyDocument,readBodyDocument,RichBodyEditor} from './RichBodyEditor';
afterEach(cleanup);
it('富文本段落和受管理产品图可还原为正文及独立图片位置',()=>{
 const editor=new Editor({extensions:bodyExtensions,content:'',contentType:'markdown'});
 const image={id:'product1',name:'产品图',caption:'产品参考图',after_block:2};
 const body='## 选购建议\n\n这是一段 **重要** 的文案。\n\n最后一段。';
 editor.commands.setContent(createBodyDocument(editor,body,[image]),{emitUpdate:false});
 const value=readBodyDocument(editor,[image]);
 expect(value.body).toContain('## 选购建议');expect(value.body).toContain('**重要**');
 expect(value.body).not.toContain('/api/knowledge/images');expect(value.images[0].after_block).toBe(2);
 expect(editor.getHTML()).toContain('/api/knowledge/images/product1');editor.destroy();
});
it('正文字体字号保存在富文本中，兼容文案正文和产品图片位置',()=>{
 const editor=new Editor({extensions:bodyExtensions,content:''});
 const image={id:'p1',name:'产品图',caption:'产品图',after_block:1};
 editor.commands.setContent(createBodyDocument(editor,'正文样式\n\n第二段',[image]),{emitUpdate:false});
 editor.chain().setTextSelection({from:1,to:5}).setMark('textStyle',{fontFamily:'楷体',fontSize:'23px'}).toggleItalic().run();
 const value=readBodyDocument(editor,[image]);
 expect(value.body).toContain('*正文样式*');expect(value.body).toContain('第二段');expect(value.images[0].after_block).toBe(1);
 expect(editor.getHTML()).toContain('font-size: 23px');expect(editor.getJSON().content?.[0].content?.[0].marks).toContainEqual({type:'textStyle',attrs:{fontFamily:'楷体',fontSize:'23px'}});
 editor.destroy();
});
it.each(['加粗','斜体','二级标题','无序列表','有序列表'])('使用%s时保留正文选区且不请求跳转到光标位置',async format=>{
 const props={body:'第一段正文\n\n第二段正文\n\n最后一段正文',images:[],choices:[],disabled:false,onChange:vi.fn(),onImages:vi.fn()};
 render(React.createElement(RichBodyEditor,props));
 const body=await screen.findByRole('textbox',{name:'正文'});
 await waitFor(()=>expect(body.textContent).toContain('最后一段正文'));
 const editor=(body as HTMLElement&{editor:Editor}).editor;
 act(()=>{editor.commands.setTextSelection({from:1,to:6});editor.view.focus();});
 await waitFor(()=>expect((screen.getByRole('button',{name:'斜体'}) as HTMLButtonElement).disabled).toBe(false));
 const scrollToCursor=vi.fn((_view:unknown)=>true);
 const handleScroll=editor.options.editorProps.handleScrollToSelection;
 editor.setOptions({editorProps:{...editor.options.editorProps,handleScrollToSelection:view=>handleScroll?.(view)||scrollToCursor(view)}});
 if(format==='二级标题'){
  fireEvent.mouseDown(screen.getByRole('combobox',{name:'段落样式'}));
  fireEvent.click(await screen.findByText('二级标题'));
 }else fireEvent.click(screen.getByRole('button',{name:format}));
 await waitFor(()=>expect(editor.view.hasFocus()).toBe(true));
 expect(editor.state.doc.textBetween(editor.state.selection.from,editor.state.selection.to)).toBe('第一段正文');
 const node={'加粗':'bold','斜体':'italic','二级标题':'heading','无序列表':'bulletList','有序列表':'orderedList'}[format]!;
 expect(editor.isActive(node,format==='二级标题'?{level:2}:{})).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'撤销'}));
 expect(editor.isActive(node,format==='二级标题'?{level:2}:{})).toBe(false);
 fireEvent.click(screen.getByRole('button',{name:'重做'}));
 expect(editor.isActive(node,format==='二级标题'?{level:2}:{})).toBe(true);
 expect(scrollToCursor).not.toHaveBeenCalled();cleanup();
});
it('加载原稿及切换只读状态不会提交空正文或误报用户修改',async()=>{
 const changed=vi.fn(),props={body:'编辑器原始正文',images:[],choices:[],disabled:false,onChange:changed,onImages:vi.fn()};
 const view=render(React.createElement(RichBodyEditor,props));
 await waitFor(()=>expect(screen.getByRole('textbox',{name:'正文'}).textContent).toContain('编辑器原始正文'));
 expect(changed).not.toHaveBeenCalled();
 view.rerender(React.createElement(RichBodyEditor,{...props,disabled:true}));
 expect(changed).not.toHaveBeenCalled();cleanup();
});
