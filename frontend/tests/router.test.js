/** Тесты хеш-роутера. */
import { describe, it, expect } from 'vitest';
import { get } from 'svelte/store';
import { route, path, params, navigate } from '../src/lib/router.js';

describe('Router', () => {
  it('парсит хеш при загрузке', () => {
    window.location.hash = '/member/polls';
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    expect(get(path)).toBe('/member/polls');
  });

  it('navigate меняет location.hash', () => {
    navigate('/admin/fees');
    expect(window.location.hash).toBe('#/admin/fees');
  });

  it('navigate + hashchange обновляет store', () => {
    navigate('/admin/people');
    // jsdom не диспатчит hashchange автоматически — диспатчим вручную
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    expect(get(path)).toBe('/admin/people');
  });

  it('парсит query params', () => {
    window.location.hash = '/member?tab=afisha&view=cal';
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    expect(get(params).get('tab')).toBe('afisha');
    expect(get(params).get('view')).toBe('cal');
  });

  it('пустой хеш даёт /', () => {
    window.location.hash = '';
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    expect(get(path)).toBe('/');
  });
});
