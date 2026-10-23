// @vitest-environment jsdom
import React from 'react';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {PriceRuleSettings} from './PriceRuleSettings';
vi.mock('./lifecycle',()=>({useData:()=>({data:[],error:'',refresh:vi.fn()})}));
vi.mock('./api',()=>({api:vi.fn()}));
afterEach(cleanup);
Object.defineProperty(window,'matchMedia',{writable:true,value:vi.fn().mockImplementation(()=>({matches:false,addListener:vi.fn(),removeListener:vi.fn(),addEventListener:vi.fn(),removeEventListener:vi.fn()}))});
it('录入规则时可维护优惠算法和套装明细，不冒充官方模板',()=>{
 render(<PriceRuleSettings/>);
 fireEvent.click(screen.getByRole('button',{name:'新增规则'}));
 expect(screen.getByRole('button',{name:'添加优惠'})).toBeTruthy();
 expect(screen.getByRole('button',{name:'添加商品或服务'})).toBeTruthy();
 expect(screen.getByText(/内部录入格式/)).toBeTruthy();
});
