// @vitest-environment jsdom
import React from 'react';
import {Editor} from '@tiptap/core';
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {RichBodyEditor,RichTextField} from './RichBodyEditor';
afterEach(cleanup);
it('没有选中文稿区域时不默认操作正文，选中标题后仅修改标题并保存自定义字号',async()=>{
 const change=vi.fn();
 render(<RichBodyEditor body="正文保留" images={[]} choices={[]} richText={{}} disabled={false} onChange={change} onImages={()=>{}}>
  <RichTextField field="title" label="作品标题" value="学习写代码" className="writer-title"/>
  <RichTextField field="intro" label="导语" value="大学生的学习场景" className="writer-intro"/>
 </RichBodyEditor>);
 await waitFor(()=>expect(screen.getByRole('textbox',{name:'作品标题'}).textContent).toBe('学习写代码'));
 expect((screen.getByRole('button',{name:'斜体'}) as HTMLButtonElement).disabled).toBe(true);
 const title=(screen.getByRole('textbox',{name:'作品标题'}) as HTMLElement&{editor:Editor}).editor;
 act(()=>{title.commands.setTextSelection({from:1,to:6});title.view.focus();});
 await waitFor(()=>expect((screen.getByRole('button',{name:'斜体'}) as HTMLButtonElement).disabled).toBe(false));
 fireEvent.mouseDown(screen.getByRole('button',{name:'斜体'}));fireEvent.click(screen.getByRole('button',{name:'斜体'}));
 await waitFor(()=>expect(screen.getByRole('textbox',{name:'作品标题'}).querySelector('em')?.textContent).toBe('学习写代码'));
 fireEvent.change(screen.getByRole('spinbutton',{name:'字号'}),{target:{value:'37'}});
 fireEvent.blur(screen.getByRole('spinbutton',{name:'字号'}));
 await waitFor(()=>expect(title.getHTML()).toContain('font-size: 37px'));
 expect(screen.getByRole('textbox',{name:'正文'}).textContent).toBe('正文保留');
 expect(change).toHaveBeenLastCalledWith(expect.objectContaining({title:'学习写代码',rich_text:expect.objectContaining({title:expect.objectContaining({source:'学习写代码'})})}));
});
it('导语与结尾标语可手改文字和样式，重新打开保留富文本',async()=>{
 const doc={type:'doc',content:[{type:'paragraph',content:[{type:'text',text:'到店试一试',marks:[{type:'italic'},{type:'textStyle',attrs:{fontSize:'26px',fontFamily:'宋体'}}]}]}]};
 const change=vi.fn();
 render(<RichBodyEditor body="正文" images={[]} choices={[]} richText={{cta:{source:'到店试一试',doc}}} disabled={false} onChange={change} onImages={()=>{}}
  footer={<RichTextField field="cta" label="结尾标语" value="到店试一试" className="writer-cta"/>}>
  <RichTextField field="intro" label="导语" value="学习场景" className="writer-intro"/>
 </RichBodyEditor>);
 await waitFor(()=>expect(screen.getByRole('textbox',{name:'结尾标语'}).querySelector('em')).toBeTruthy());
 expect(screen.getByRole('textbox',{name:'结尾标语'}).innerHTML).toContain('26px');
 const intro=(screen.getByRole('textbox',{name:'导语'}) as HTMLElement&{editor:Editor}).editor;
 act(()=>{intro.commands.setTextSelection({from:1,to:5});intro.view.focus();});
 fireEvent.click(screen.getByRole('button',{name:'加粗'}));
 await waitFor(()=>expect(screen.getByRole('textbox',{name:'导语'}).querySelector('strong')).toBeTruthy());
 expect(change).toHaveBeenLastCalledWith(expect.objectContaining({intro:'学习场景'}));
});
