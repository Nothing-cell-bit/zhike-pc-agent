// @vitest-environment jsdom
import React from 'react';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,expect,it} from 'vitest';
import {ReferencePrice,referencePrices,snapshotTime} from './ReferencePrice';

afterEach(cleanup);
const name='HUAWEI MateBook 14（鸿蒙版）';
const row=(values:Record<string,string>={})=>({
  '记录ID':'one','规范产品名称':name,'页面金额（元）':'5899','精确款式':'16GB/512GB/原野绿',
  '价格类型':'官方商城页面价','核验时间':'2026-10-17T14:40:00-05:00',
  '官方URL':'https://item.vmall.com/product/comdetail/index.html?prdId=1',
  '条件摘要':'积分8倍抵现；赠品以结算页为准','库存状态':'当时可购买',...values,
});

it('显示参考价、北京时间快照、对应配置及原始条件，不自行扣券',()=>{
  render(<ReferencePrice productName={name} prices={[row({'价格类型':'当前商城页面价（未扣优惠券）','条件摘要':'500元优惠券；资格待核验'})]}/>);
  expect(screen.getByText('参考价')).toBeTruthy();
  expect(screen.getByText('5,899',{exact:false})).toBeTruthy();
  expect(screen.getByText('2026-10-18')).toBeTruthy();
  expect(screen.queryByText('500元优惠券；资格待核验')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'价格详情'}));
  expect(screen.getByText(/快照日期（北京时间）：2026-10-18 03:40/)).toBeTruthy();
  expect(screen.getByText(/对应款式：16GB\/512GB\/原野绿/)).toBeTruthy();
  expect(screen.getByText('500元优惠券；资格待核验')).toBeTruthy();
  expect(screen.queryByText('5,399',{exact:false})).toBeNull();
  expect(screen.getByRole('link',{name:'查看官方来源 ↗'}).getAttribute('href')).toContain('https://item.vmall.com/');
});

it('优先具体SKU的页面快照，切换配置后同步金额、日期和条件',()=>{
  render(<ReferencePrice productName={name} prices={[
    row({'记录ID':'estimated','价格类型':'预估到手价','页面金额（元）':'4999','精确款式':'专区默认展示款'}),
    row(),row({'记录ID':'two','页面金额（元）':'6599','精确款式':'24GB/512GB/原野绿','核验时间':'2026-10-17T13:40:00-05:00','条件摘要':'另一个配置的条件'}),
  ]}/>);
  fireEvent.click(screen.getByRole('button',{name:'价格详情'}));
  const select=screen.getByRole('combobox',{name:'切换配置或价格记录'}) as HTMLSelectElement;
  expect(select.value).toBe('one');
  fireEvent.change(select,{target:{value:'two'}});
  expect(screen.getByText(/快照日期（北京时间）：2026-10-18 02:40/)).toBeTruthy();
  expect(screen.getByText('另一个配置的条件')).toBeTruthy();
  expect(screen.getByText(/对应款式：24GB/)).toBeTruthy();
});

it('精确隔离版本和配件，Pro只使用已确认的鸿蒙版别名',()=>{
  expect(referencePrices(name,[row(),row({'规范产品名称':'HUAWEI MateBook 14 酷睿 Ultra'}),row({'规范产品名称':'华为鼠标','条件摘要':name})]).entries).toHaveLength(1);
  const result=referencePrices('HUAWEI MateBook Pro',[row({'规范产品名称':'HUAWEI MateBook Pro（鸿蒙版）'}),row({'规范产品名称':'HUAWEI MateBook Pro S'})]);
  expect(result.entries).toHaveLength(1);
  expect(result.entries[0]['规范产品名称']).toBe('HUAWEI MateBook Pro（鸿蒙版）');
});

it('空金额、零、错误日期、非官方或脚本链接均不能成为参考价',()=>{
  const rows=[row({'页面金额（元）':''}),row({'页面金额（元）':'0'}),row({'核验时间':'不是日期'}),row({'官方URL':'javascript:alert(1)'}),row({'官方URL':'https://vmall.com.evil.example/product'})];
  expect(referencePrices(name,rows).entries).toHaveLength(0);
  render(<ReferencePrice productName={name} prices={[]}/>);
  expect(screen.getByText('价格待咨询')).toBeTruthy();
  expect(screen.queryByText('¥0')).toBeNull();
});

it('历史起价标注起价及下架状态，不将历史来源改成当前成交价',()=>{
  render(<ReferencePrice productName={name} prices={[
    row({'价格类型':'官网参考起价','页面金额（元）':'6799'}),
    row({'记录ID':'status','页面金额（元）':'','价格类型':'当前商城状态','库存状态':'已下架','核验时间':'2026-10-17T14:51:00-05:00'}),
  ]}/>);
  expect(screen.getByText('历史参考价')).toBeTruthy();
  expect(screen.getByText('起',{exact:true})).toBeTruthy();
  expect(screen.queryByText(/快照中原商城商品页已下架/)).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'价格详情'}));
  expect(screen.getByText(/快照中原商城商品页已下架/)).toBeTruthy();
});

it('保留日期记录，不将未知时区的时间当作北京时间',()=>{
  expect(snapshotTime('2026-10-17')).toBe('2026-10-17');
  expect(snapshotTime('2026-10-17T14:40:00')).toBe('');
});
