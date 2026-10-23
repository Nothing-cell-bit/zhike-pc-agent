// @vitest-environment jsdom
import React from 'react';
import {cleanup,render,screen} from '@testing-library/react';
import {afterEach,expect,it} from 'vitest';
import {PlatformArticlePreview} from './PlatformArticlePreview';
afterEach(cleanup);
it('朋友圈预览只有发布短文，不展示作品库标题、导语和独立结尾',()=>{
 render(<PlatformArticlePreview work={{brief:{platform:'朋友圈'}}} content={{title:'内部作品名',intro:'不应展示导语',body:'带着课程软件清单来看看电脑。',cta:'不应重复结尾',tags:['内部标签'],images:[]}}/>);
 expect(screen.getByText('带着课程软件清单来看看电脑。')).toBeTruthy();
 for(const text of ['内部作品名','不应展示导语','不应重复结尾','内部标签'])expect(screen.queryByText(text)).toBeNull();
 expect(screen.queryByRole('heading',{level:1})).toBeNull();
});
it('小红书预览有笔记标题与话题，公众号预览使用文章样式',()=>{
 const content={title:'上课写代码，先看这两点',body:'- 核对系统\n- 试试键盘',tags:['学习选本'],images:[]};
 const view=render(<PlatformArticlePreview work={{brief:{platform:'小红书'}}} content={content}/>);
 expect(screen.getByRole('heading',{name:content.title})).toBeTruthy();expect(screen.getByText('#学习选本')).toBeTruthy();
 view.rerender(<PlatformArticlePreview work={{brief:{platform:'公众号'}}} content={content}/>);
 expect(view.container.querySelector('.platform-wechat')).toBeTruthy();
});
