// @vitest-environment jsdom
import React from 'react';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ConsultationPricing} from './ConsultationPricing';
import {api} from './api';
vi.mock('./api',()=>({api:vi.fn()}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
const products=[{id:'pc',name:'HUAWEI MateBook 14 酷睿 Ultra'}];
const row={'记录ID':'one','规范产品名称':products[0].name,'页面金额（元）':'6999','精确款式':'Ultra 5 / 16GB / 1TB','价格类型':'官方商城页面价','核验时间':'2026-10-18','官方URL':'https://www.vmall.com/product/1.html','条件摘要':'适用条件尚待当日核验'};

it('客服可选具体型号查看参考价并采用含配置、日期和条件的草稿，不自动发送',async()=>{
 vi.mocked(api).mockResolvedValue({prices:[row]});const adopt=vi.fn();
 render(<ConsultationPricing products={products} messages={[{content:products[0].name}]} selectedProduct="" onSelect={vi.fn()} editable onAdopt={adopt} onGenerate={vi.fn()}/>);
 await waitFor(()=>expect(screen.getByText('6,999',{exact:false})).toBeTruthy());
 expect(adopt).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'采用参考价回复'}));
 expect(adopt).toHaveBeenCalledTimes(1);const text=adopt.mock.calls[0][0];
 for(const part of ['6999','16GB','1TB','2026-10-18','适用条件尚待当日核验','实际'])expect(text).toContain(part);
});

it('型号不明确时要求选择，不自动将系列名当型号',()=>{
 render(<ConsultationPricing products={products} messages={[{content:'Mate多少钱'}]} selectedProduct="" onSelect={vi.fn()} editable onAdopt={vi.fn()} onGenerate={vi.fn()}/>);
 expect(screen.getByText('请先选择具体型号')).toBeTruthy();expect(api).not.toHaveBeenCalled();
});
