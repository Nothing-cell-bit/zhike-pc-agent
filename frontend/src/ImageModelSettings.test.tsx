// @vitest-environment jsdom
import React from 'react';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ImageModelSettings} from './ImageModelSettings';
import {api} from './api';
vi.mock('./api',()=>({api:vi.fn()}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
const initial={base_url:'https://images.example/v1',model:'my-image-model',key_configured:true,configured:true,source:'environment'};
it('图片API可手填保存，密钥不回填且保存后清空',async()=>{
 vi.mocked(api).mockResolvedValue(initial);
 render(<ImageModelSettings onSaved={vi.fn()}/>);
 await screen.findByDisplayValue(initial.base_url);
 const key=screen.getByLabelText('图片 API Key') as HTMLInputElement;expect(key.value).toBe('');
 fireEvent.change(screen.getByLabelText('图片模型名称'),{target:{value:'new-image-model'}});
 fireEvent.change(key,{target:{value:'private-image-test-value'}});
 fireEvent.click(screen.getByRole('button',{name:'保存图片配置'}));
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/admin/image-model','PUT',{base_url:initial.base_url,model:'new-image-model',api_key:'private-image-test-value'}));
 await waitFor(()=>expect(key.value).toBe(''));
 expect(screen.getByText(/图片配置已保存/)).toBeTruthy();
});
it('连接测试不创建生图任务，并说明目录检查的边界',async()=>{
 vi.mocked(api).mockResolvedValueOnce(initial).mockResolvedValueOnce({ok:true,message:'图片服务鉴权和模型列表检查通过'});
 render(<ImageModelSettings onSaved={vi.fn()}/>);
 await screen.findByDisplayValue(initial.base_url);
 fireEvent.click(screen.getByRole('button',{name:'测试当前图片配置'}));
 await screen.findByText('图片服务鉴权和模型列表检查通过');
 expect(api).toHaveBeenCalledWith('/admin/check-image-model','POST');
 expect(screen.getByText(/测试只查询模型列表，不创建生图任务/)).toBeTruthy();
});
