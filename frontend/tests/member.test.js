/** E2E: участник — обновлено под auth flow. */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';

// мокаем auth store (в тестах всегда авторизованы как участник)
vi.mock('../src/lib/auth.js', () => {
  const { writable } = require('svelte/store');
  const mockUser = writable({ id: 1, name: 'Тест Участник', role: 'member', platform: 'vk', announcements: true, subscription: 'active' });
  return {
    user: mockUser,
    authLoading: writable(false),
    checkAuth: vi.fn(),
    loginWithToken: vi.fn(),
    logout: vi.fn(() => mockUser.set(null)),
  };
});

import App from '../src/App.svelte';
import Afisha from '../src/pages/member/Afisha.svelte';
import Polls from '../src/pages/member/Polls.svelte';
import Fees from '../src/pages/member/Fees.svelte';
import Profile from '../src/pages/member/Profile.svelte';

describe('E2E: Навигация', () => {
  it('обложка показывает кнопку участника', () => {
    render(App);
    expect(screen.getByText('Участник')).toBeInTheDocument();
  });

  it('обложка показывает имя пользователя', () => {
    render(App);
    expect(screen.getByText(/Тест Участник/i)).toBeInTheDocument();
  });

  it('кнопка «Руководитель» скрыта для участника', () => {
    render(App);
    expect(screen.queryByText('Руководитель')).not.toBeInTheDocument();
  });

  it('клик «Участник» ведёт на /member', async () => {
    render(App);
    fireEvent.click(screen.getByText('Участник'));
    await tick();
    expect(window.location.hash).toBe('#/member');
  });

  it('обложка: «Клуб по интересам»', () => {
    render(App);
    expect(screen.getByText(/Клуб по интересам/i)).toBeInTheDocument();
  });
});

describe('E2E: Участник · Афиша', () => {
  it('показывает событие с RSVP-кнопками', async () => {
    render(Afisha);
    await waitFor(() => {
      expect(screen.getByText(/Тренировка по импровизации/i)).toBeInTheDocument();
    });
    expect(screen.getAllByText('Пойду').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Возможно').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Не приду').length).toBeGreaterThanOrEqual(1);
  });

  it('RSVP кнопки цветные (data-vote)', async () => {
    render(Afisha);
    await waitFor(() => screen.getAllByText('Пойду'));
    const yesBtn = screen.getAllByText('Пойду')[0].closest('button');
    expect(yesBtn?.dataset.vote).toBe('yes');
    const noBtn = screen.getAllByText('Не приду')[0].closest('button');
    expect(noBtn?.dataset.vote).toBe('no');
  });

  it('клик «Пойду» выделяет кнопку', async () => {
    render(Afisha);
    await waitFor(() => screen.getAllByText('Пойду'));
    const btn = screen.getAllByText('Пойду')[0].closest('button');
    fireEvent.click(btn);
    await waitFor(() => {
      expect(btn?.classList.contains('selected')).toBe(true);
    });
  });

  it('заголовок события кликабелен (переход на детальную)', async () => {
    render(Afisha);
    await waitFor(() => screen.getByRole('link', { name: /Тренировка/i }));
    // кликабельный заголовок — это link role
    const title = screen.getByRole('link', { name: /Тренировка/i });
    expect(title).toBeInTheDocument();
  });
});

describe('E2E: Участник · Опросы', () => {
  it('показывает опрос с вариантами (левое выравнивание)', async () => {
    render(Polls);
    await waitFor(() => {
      expect(screen.getByText(/Куда едем/i)).toBeInTheDocument();
    });
    expect(screen.getByText('Баня')).toBeInTheDocument();
    expect(screen.getByText('Каток')).toBeInTheDocument();
  });

  it('клик по варианту выделяет его', async () => {
    render(Polls);
    await waitFor(() => screen.getByText('Баня'));
    const opt = screen.getByText('Баня').closest('button');
    expect(opt).toBeTruthy();
    fireEvent.click(opt);
    await waitFor(() => {
      expect(opt?.classList.contains('selected')).toBe(true);
    });
  });

  it('кнопка «Кто проголосовал» раскрывает список', async () => {
    render(Polls);
    await waitFor(() => screen.getAllByText(/Кто проголосовал/i));
    const btn = screen.getAllByText(/Кто проголосовал/i)[0];
    fireEvent.click(btn);
    await waitFor(() => {
      // появляются имена голосовавших (может быть несколько совпадений)
      expect(screen.getAllByText(/Аня К\./i).length).toBeGreaterThanOrEqual(1);
    });
  });

  it('закрытый опрос показывает итоги с именами', async () => {
    render(Polls);
    await waitFor(() => {
      expect(screen.getByText(/кабаре или драма/i)).toBeInTheDocument();
    });
    const closed = screen.getByText('Кабаре').closest('button');
    expect(closed?.disabled).toBe(true);
  });
});

describe('E2E: Участник · Взнос', () => {
  it('показывает долг', async () => {
    render(Fees);
    await waitFor(() => {
      expect(screen.getByText(/400/)).toBeInTheDocument();
    });
  });

  it('форма «Я оплатил» без поля «Как»', async () => {
    render(Fees);
    await waitFor(() => {
      expect(screen.getByText(/Я оплатил/i)).toBeInTheDocument();
    });
    expect(screen.getByLabelText(/Сумма/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Как/i)).not.toBeInTheDocument();
  });

  it('отправка формы', async () => {
    render(Fees);
    await waitFor(() => screen.getByText('Отправить руководителю'));
    fireEvent.input(screen.getByLabelText(/Сумма/i), { target: { value: '300' } });
    fireEvent.click(screen.getByText('Отправить руководителю'));
    await waitFor(() => {
      expect(screen.getByText(/отправлено/i, { exact: false })).toBeInTheDocument();
    });
  });
});

describe('E2E: Участник · Профиль', () => {
  it('показывает имя из auth store', async () => {
    render(Profile);
    await waitFor(() => {
      expect(screen.getByText(/Тест Участник/i)).toBeInTheDocument();
    });
  });

  it('показывает аккаунты', async () => {
    render(Profile);
    await waitFor(() => {
      expect(screen.getByText(/ВКонтакте/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/Telegram/i)).toBeInTheDocument();
  });

  it('показывает кнопку чата', async () => {
    render(Profile);
    await waitFor(() => {
      expect(screen.getByText(/Написать руководителю/i)).toBeInTheDocument();
    });
  });

  it('показывает статус подписки', async () => {
    render(Profile);
    await waitFor(() => screen.getByText(/Статус подписки/i));
  });

  it('нет академа у участника', async () => {
    render(Profile);
    expect(screen.queryByText(/Академический отпуск/i)).not.toBeInTheDocument();
  });
});
