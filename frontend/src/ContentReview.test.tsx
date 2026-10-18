// @vitest-environment jsdom
import React from 'react';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ContentReview} from './ContentReview';

afterEach(cleanup);
const work={version:1,content:{pending:['活动待核实']},report:{status:'needs_review',issues:[{type:'事实',text:'续航描述缺少依据'}],pending:['活动待核实']}};
const handlers=()=>({onCheck:vi.fn(),onRepair:vi.fn(),onApprove:vi.fn().mockResolvedValue(undefined)});
it('列出具体问题和去重后的待确认项，提供自动调整',()=>{
 const h=handlers();render(<ContentReview work={work} dirty={false} {...h}/>);
 expect(screen.getByText(/续航描述缺少依据/)).toBeTruthy();
 expect(screen.getAllByText(/活动待核实/)).toHaveLength(1);
 fireEvent.click(screen.getByRole('button',{name:'自动调整并检查'}));expect(h.onRepair).toHaveBeenCalledOnce();
});
it('人工通过展示原检查项并提交说明，失败可重试',async()=>{
 const h=handlers();h.onApprove.mockRejectedValueOnce(new Error('版本已变化'));
 render(<ContentReview work={work} dirty={false} {...h}/>);
 fireEvent.click(screen.getByRole('button',{name:'人工确认通过'}));
 fireEvent.change(screen.getByLabelText('确认说明'),{target:{value:'已核实当日活动'}});
 fireEvent.click(screen.getByRole('button',{name:/确认通过当前版本/}));
 await waitFor(()=>expect(screen.getByText('版本已变化')).toBeTruthy());
 fireEvent.click(screen.getByRole('button',{name:/确认通过当前版本/}));
 await waitFor(()=>expect(h.onApprove).toHaveBeenCalledTimes(2));
 expect(h.onApprove).toHaveBeenLastCalledWith('已核实当日活动');
});
it('修改未保存或任务处理中时不可批准或自动调整',()=>{
 const h=handlers();const {rerender}=render(<ContentReview work={work} dirty {...h}/>);
 for(const name of ['自动调整并检查','人工确认通过','重新检查'])expect((screen.getByRole('button',{name}) as HTMLButtonElement).disabled).toBe(true);
 rerender(<ContentReview work={work} dirty={false} busy {...h}/>);
 expect((screen.getByRole('button',{name:'人工确认通过'}) as HTMLButtonElement).disabled).toBe(true);
});
it('人工通过后明确展示确认人，保留原始检查明细',()=>{
 render(<ContentReview work={{...work,report:{...work.report,status:'manual_passed',approval:{display_name:'门店顾问',note:'已核实',approved_at:'2026-10-18T01:00:00Z'}}}} dirty={false} {...handlers()}/>);
 expect(screen.getByText('人工已通过')).toBeTruthy();
 expect(screen.getByText(/门店顾问/)).toBeTruthy();
 expect(screen.getByText(/续航描述缺少依据/)).toBeTruthy();
 expect(screen.queryByRole('button',{name:'人工确认通过'})).toBeNull();
});
