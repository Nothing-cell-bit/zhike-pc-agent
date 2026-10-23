// @vitest-environment jsdom
import React from 'react';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {CustomerNeeds} from './CustomerNeeds';

afterEach(cleanup);
const analysis={user:{value:'大二学生'},progress:{value:'想换电脑'},budget:{value:'1万元以内'},tasks:{value:'待确认'},next_question:{state:'ready',field:'tasks',text:'平时主要用电脑做什么？'}};

it('七个字段明确区分，没聊到的内容显示尚未了解',()=>{
 render(<CustomerNeeds analysis={analysis} editable onEdit={vi.fn()} onAdopt={vi.fn()}/>);
 for(const label of ['客户身份','购机意向','购机预算','主要用途','必用软件','主要顾虑','下一步安排'])expect(screen.getByText(label,{exact:true})).toBeTruthy();
 expect(screen.getAllByText('尚未了解').length).toBe(4);
 expect(screen.queryByText('使用任务')).toBeNull();expect(screen.queryByText('查看对话依据')).toBeNull();
});
it('采用追问仅通知父组件填入草稿，未自动发消息',()=>{
 const adopt=vi.fn();render(<CustomerNeeds analysis={analysis} editable onEdit={vi.fn()} onAdopt={adopt}/>);
 expect(adopt).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'采用到输入框'}));expect(adopt).toHaveBeenCalledExactlyOnceWith('平时主要用电脑做什么？');
});
it('未负责会话时不能采用追问或修改需求',()=>{
 render(<CustomerNeeds analysis={analysis} editable={false} onEdit={vi.fn()} onAdopt={vi.fn()}/>);
 expect((screen.getByRole('button',{name:'采用到输入框'}) as HTMLButtonElement).disabled).toBe(true);
 expect((screen.getByRole('button',{name:'修改必用软件'}) as HTMLButtonElement).disabled).toBe(true);
});
it('客户尚未答复或正在更新时不提供重复追问按钮',()=>{
 const {rerender}=render(<CustomerNeeds analysis={{...analysis,next_question:{state:'waiting',text:'先等客户回复上一条问题。'}}} editable onEdit={vi.fn()} onAdopt={vi.fn()}/>);
 expect(screen.queryByRole('button',{name:'采用到输入框'})).toBeNull();
 rerender(<CustomerNeeds analysis={analysis} editable updating onEdit={vi.fn()} onAdopt={vi.fn()}/>);
 expect(screen.queryByRole('button',{name:'采用到输入框'})).toBeNull();
});
it('客服已修正的购机意向明确显示锁定且仍可再次修改',()=>{
 const edit=vi.fn();render(<CustomerNeeds analysis={{...analysis,progress:{value:'想换电脑',manual:true}}} editable onEdit={edit} onAdopt={vi.fn()}/>);
 expect(screen.getByText('已锁定')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'修改购机意向'}));
 expect(edit).toHaveBeenCalledWith('progress','想换电脑');
});
