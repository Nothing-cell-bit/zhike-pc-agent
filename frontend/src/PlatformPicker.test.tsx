// @vitest-environment jsdom
import React from 'react';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {PlatformPicker} from './PlatformPicker';
afterEach(cleanup);
it('解释三种不同产物，不把海报列为发布平台',()=>{
 const changed=vi.fn();render(<PlatformPicker value="公众号" onChange={changed}/>);
 expect(screen.getByRole('radiogroup',{name:'发布平台'})).toBeTruthy();
 expect(screen.getByRole('radio',{name:/公众号.*深度文章/}).getAttribute('aria-checked')).toBe('true');
 expect(screen.getByRole('radio',{name:/小红书.*场景笔记/})).toBeTruthy();
 fireEvent.click(screen.getByRole('radio',{name:/朋友圈.*自然短文/}));expect(changed).toHaveBeenCalledWith('朋友圈');
 expect(screen.queryByRole('radio',{name:/海报/})).toBeNull();
});
