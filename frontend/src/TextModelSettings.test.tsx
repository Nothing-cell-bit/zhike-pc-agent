// @vitest-environment jsdom
import React from 'react';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, expect, it, vi} from 'vitest';
import {TextModelSettings} from './TextModelSettings';
import {api} from './api';
vi.mock('./api',()=>({api:vi.fn()}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
const current={base_url:'https://provider.example/v1',model:'old-model',key_configured:true,configured:true,source:'environment'};
it('管理员可保存配置，密钥不回填；保存后清除输入并提示立即生效',async()=>{
 vi.mocked(api).mockResolvedValue(current);
 render(<TextModelSettings onSaved={vi.fn()}/>);
 await screen.findByDisplayValue(current.base_url);
 const key=screen.getByLabelText('API Key') as HTMLInputElement;
 expect(key.value).toBe('');
 fireEvent.change(screen.getByLabelText('模型名称'),{target:{value:'new-model'}});
 fireEvent.change(key,{target:{value:'new-private-value'}});
 fireEvent.click(screen.getByRole('button',{name:'保存模型配置'}));
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/admin/text-model','PUT',{base_url:current.base_url,model:'new-model',api_key:'new-private-value'}));
 await waitFor(()=>expect(key.value).toBe(''));
 expect(screen.getByText(/保存成功，后续任务立即使用新配置/)).toBeTruthy();
});
it('测试失败有明确反馈，保留配置供修正',async()=>{
 vi.mocked(api).mockResolvedValueOnce(current).mockResolvedValueOnce({ok:false,message:'模型鉴权失败'});
 render(<TextModelSettings onSaved={vi.fn()}/>);
 await screen.findByDisplayValue(current.model);
 fireEvent.click(screen.getByRole('button',{name:'测试当前已保存配置'}));
 await screen.findByText('模型鉴权失败');
 expect(api).toHaveBeenCalledWith('/admin/check-model','POST');
});
