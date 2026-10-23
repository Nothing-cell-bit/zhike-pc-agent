// @vitest-environment jsdom
import React from 'react';
import {fireEvent,render,screen,cleanup} from '@testing-library/react';
import {afterEach,expect,it} from 'vitest';
import {ChatMessageContent} from './ChatMessageContent';
afterEach(cleanup);
const legacy='屏幕为16英寸IPS，1920×1200分辨率。\n您主要打算用它做什么？\n\n| 机型 | 处理器（资料原文） | 重量（资料原文） |\n| --- | --- | --- |\n| HUAWEI MateBook D 16 2024 | i9-13900H<br><br>*仅限 Windows 版本搭载。 | 约 1.68 kg |';
it('shows the conversational answer and readable expandable specs instead of pipe/br markup',()=>{
 const {container}=render(<ChatMessageContent text={legacy}/>);
 expect(screen.getByText(/屏幕为16英寸IPS/)).toBeTruthy();
 const details=container.querySelector('details')!;
 expect(details).toBeTruthy();expect(details.open).toBe(false);
 fireEvent.click(screen.getByText('查看产品参数'));
 expect(screen.getByText('处理器')).toBeTruthy();
 expect(container.textContent).toContain('仅限 Windows 版本搭载。');
 expect(container.textContent).not.toMatch(/<br>|资料原文|\| ---/);
});
it('treats tags in values as text and never executes supplied HTML',()=>{
 const {container}=render(<ChatMessageContent text={legacy.replace('i9-13900H','<img src=x onerror=alert(1)>')}/>);
 expect(container.querySelector('img')).toBeNull();
 expect(container.textContent).toContain('<img src=x onerror=alert(1)>');
});
it('keeps normal and customer text intact',()=>{
 const {container}=render(<ChatMessageContent text={legacy} customer/>);
 expect(container.querySelector('details')).toBeNull();
 expect(container.textContent).toBe(legacy);
});
it('keeps an empty historical draft from crashing the chat panel',()=>{
 const {container}=render(<ChatMessageContent text={undefined}/>);
 expect(container.textContent).toBe('');
});
