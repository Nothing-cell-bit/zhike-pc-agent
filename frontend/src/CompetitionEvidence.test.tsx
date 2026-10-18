// @vitest-environment jsdom
import React from 'react';
import {cleanup,render,screen} from '@testing-library/react';
import {afterEach,expect,it} from 'vitest';
import {CompetitionEvidence,ArticleBody,TaskQuestions} from './CompetitionEvidence';

afterEach(cleanup);
it('公开样例明确说明省略资料，不冒充ima或本地知识库核验',()=>{
 render(<CompetitionEvidence work={{brief:{},content:{source_type:'sample',title:'历史文案'},report:{status:'needs_review',ima_verified:false}}}/>);
 expect(screen.getByText(/公开历史样例/)).toBeTruthy();
 expect(screen.getByText(/公开副本未附原图及资料快照/)).toBeTruthy();
 expect(screen.queryByText(/知识来源：ima/)).toBeNull();
 expect(screen.queryByText(/本地 ZIP/)).toBeNull();
});
it('显示四部分依据、未知阶段和本地图源，不冒充ima',()=>{
 render(<CompetitionEvidence work={{brief:{audience:'学生',scene:'课堂笔记',platform:'小红书'},content:{title:'选购清单',body:'核对任务',images:[],sources:[]},report:{status:'unchecked'}}}/>);
 for(const title of ['一、场景判断','二、知识库依据','三、图文软文','四、核验结果'])expect(screen.getByRole('heading',{name:title})).toBeTruthy();
 expect(screen.getAllByText(/待确认/).length).toBeGreaterThan(0);
 expect(screen.getByText(/本地 ZIP/)).toBeTruthy();
});
it('图片实际出现在指定正文块后，兼容旧作品的位置',()=>{
 const {container}=render(<ArticleBody content={{body:'第一段\n\n第二段',images:[{id:'a',name:'a.png',caption:'课堂',after_block:1},{id:'b',name:'b.png',caption:'差旅',position:'第2段后'}]}}/>);
 expect(Array.from(container.querySelectorAll('.prose,figure')).map(x=>x.textContent)).toEqual(['第一段','课堂','第二段','差旅']);
});
it('冲突任务能看见人工确认问题',()=>{
 render(<TaskQuestions result={{needs_confirmation:['同配置重量冲突'],questions:['请人工确认后重试']}}/>);
 expect(screen.getByRole('status').textContent).toContain('同配置重量冲突');
 expect(screen.getByText('请人工确认后重试')).toBeTruthy();
});
it('正文不能通过Markdown或HTML夹带外部图片',()=>{
 const {container}=render(<ArticleBody content={{body:'![假图](https://outside.test/fake.png)\n\n<img src="https://outside.test/fake.png">',images:[]}}/>);
 expect(container.querySelector('img')).toBeNull();
});
it('给出事实、配图选择理由和冲突原因',()=>{
 render(<CompetitionEvidence work={{brief:{},content:{strategy:'从学习切入',strategy_current:false,images:[{id:'a',name:'课堂.png',caption:'笔记场景',source:'https://consumer.huawei.com/',position:'正文第1块后',selection_reason:'匹配课堂'}],sources:[{id:'s',title:'产品参数',version:'v1'}]},report:{status:'needs_review',blocked:true,issues:[{type:'资料冲突',text:'重量口径矛盾'}],claims:[{text:'事实点',source_id:'s'}]}}}/>);
 expect(screen.getByText(/重量口径矛盾/)).toBeTruthy();expect(screen.getByText(/匹配课堂/)).toBeTruthy();expect(screen.getByText(/事实点/)).toBeTruthy();
 expect(screen.getByText(/策略.*修改前/)).toBeTruthy();
});
it('ima作品显示真实图源，回退稿明确标记本地与原因',()=>{
 const {rerender}=render(<CompetitionEvidence work={{brief:{},content:{source_type:'ima',knowledge_base_name:'比赛库'},report:{status:'passed',ima_verified:true}}}/>);
 expect(screen.getByText(/知识来源：ima.*比赛库/)).toBeTruthy();expect(screen.queryByText(/本地 ZIP/)).toBeNull();
 rerender(<CompetitionEvidence work={{brief:{},content:{source_type:'local_zip',fallback_reason:'ima 连接超时'},report:{status:'passed'}}}/>);
 expect(screen.getByText(/ima 连接超时/)).toBeTruthy();expect(screen.getByText(/本地 ZIP/)).toBeTruthy();
});
