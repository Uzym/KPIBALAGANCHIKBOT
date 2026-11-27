/** Auth store: текущий пользователь, логин/логаут. */
import { writable } from 'svelte/store';

export const user = writable(null);
export const authLoading = writable(true);

export async function checkAuth() {
  try {
    const resp = await fetch('/api/auth/me');
    if (resp.ok) {
      const data = await resp.json();
      user.set(data);
    } else {
      user.set(null);
    }
  } catch {
    user.set(null);
  }
  authLoading.set(false);
}

export async function loginWithToken(token) {
  const resp = await fetch(`/api/auth/login?t=${encodeURIComponent(token)}`);
  if (resp.ok) {
    const data = await resp.json();
    user.set(data);
    return data;
  }
  const err = await resp.json().catch(() => ({}));
  throw new Error(err.error || 'Не удалось войти');
}

export async function logout() {
  await fetch('/api/auth/logout', { method: 'POST' });
  user.set(null);
}

// при загрузке модуля — проверить сессию
checkAuth();
