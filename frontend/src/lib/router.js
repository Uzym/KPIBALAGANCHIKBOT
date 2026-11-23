/** Хеш-роутер на Svelte stores. Простой, без зависимостей. */
import { writable, derived } from 'svelte/store';

function parseHash() {
  const hash = location.hash.slice(1) || '/';
  const [path, queryString] = hash.split('?');
  const params = new URLSearchParams(queryString || '');
  return { path, params };
}

export const route = writable(parseHash());

export const path = derived(route, r => r.path);
export const params = derived(route, r => r.params);

export function navigate(to) {
  location.hash = to.startsWith('/') ? to : `/${to}`;
}

window.addEventListener('hashchange', () => {
  route.set(parseHash());
});
