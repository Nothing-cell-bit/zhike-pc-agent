// @vitest-environment jsdom
import React from 'react';
import {render,screen} from '@testing-library/react';
import {expect,it} from 'vitest';
import {QuoteCard} from './QuoteCard';
it('renders server amounts, quantities and validity without internal approval details',()=>{
 render(<QuoteCard card={{type:'quote',quotes:[{name:'测试电脑',variant:'32GB / 1TB',sku_ref:'SALE-32',level:'L2',quantity:2,unit_minor:500000,fees_minor:1000,deduction_minor:50000,total_minor:951000,valid_until:'2026-10-19T10:00:00Z',rule_id:'private-rule'}]}}/>);
 expect(screen.getByText('¥9,510.00')).toBeTruthy();expect(screen.getByText('2 台')).toBeTruthy();
 expect(screen.getByText('SALE-32')).toBeTruthy();expect(screen.queryByText('private-rule')).toBeNull();
 expect(screen.getByText(/北京时间/).textContent).toContain('18:00');
});
