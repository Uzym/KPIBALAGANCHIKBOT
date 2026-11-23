/** E2E: участник — полные пользовательские сценарии через UI. */
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';

import App from '../src/App.svelte';
import Afisha from '../src/pages/member/Afisha.svelte';
import Polls from '../src/pages/member/Polls.svelte';
import Fees from '../src/pages/member/Fees.svelte';
import Profile from '../src/pages/member/Profile.svelte';

describe('E2E: Навигация', () => {
  it('обложка показывает обе кнопки', () => {
    render(App);
    expect(screen.getByText('Участник')).toBeInTheDocument();
    expect(screen.getByText('Руководитель')).toBeInTheDocument();
  });

  it('клик «Участник» ведёт на /member', async () => {
    render(App);
    fireEvent.click(screen.getByText('Участник'));
    await tick();
    expect(window.location.hash).toBe('#/member');
  });

  it('клик «Руководитель» ведёт на /admin', async () => {
    render(App);
    fireEvent.click(screen.getByText('Руководитель'));
    await tick();
    expect(window.location.hash).toBe('#/admin');
  });
});

describe('E2E: Участник · Афиша', () => {
  it('показывает ближайшее событие с RSVP-кнопками', async () => {
    render(Afisha);
    await waitFor(() => {
      expect(screen.getByText(/Тренировка по импровизации/i)).toBeInTheDocument();
    });
    // RSVP-кнопки: «Пойду» может быть несколько (для разных событий) — проверяем наличие
    expect(screen.getAllByText('Пойду').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Возможно').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Не приду').length).toBeGreaterThanOrEqual(1);
  });

  it('клик «Пойду» меняет состояние кнопки', async () => {
    render(Afisha);
    await waitFor(() => screen.getAllByText('Пойду'));

    const btn = screen.getAllByText('Пойду')[0].closest('button');
    expect(btn).toBeTruthy();
    fireEvent.click(btn);
    await waitFor(() => {
      // после клика кнопка выделяется (класс selected)
      expect(btn?.classList.contains('selected')).toBe(true);
    });
  });

  it('переключение на календарь показывает сетку дней', async () => {
    render(Afisha);
    await waitFor(() => screen.getByText('Календарь'));

    fireEvent.click(screen.getByText('Календарь'));
    await waitFor(() => {
      expect(screen.getByText('Пн')).toBeInTheDocument();
      expect(screen.getByText('Ср')).toBeInTheDocument();
      expect(screen.getByText('Сб')).toBeInTheDocument();
    });
  });

  it('переключение обратно на список', async () => {
    render(Afisha);
    await waitFor(() => screen.getByText('Календарь'));
    fireEvent.click(screen.getByText('Календарь'));
    await tick();
    fireEvent.click(screen.getByText('Список'));
    await waitFor(() => {
      expect(screen.getByText(/Тренировка по импровизации/i)).toBeInTheDocument();
    });
  });
});

describe('E2E: Участник · Опросы', () => {
  it('показывает активный опрос с вариантами', async () => {
    render(Polls);
    await waitFor(() => {
      expect(screen.getByText(/Куда едем/i)).toBeInTheDocument();
    });
    expect(screen.getByText('Баня')).toBeInTheDocument();
    expect(screen.getByText('Каток')).toBeInTheDocument();
    expect(screen.getByText('Квартирник')).toBeInTheDocument();
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

  it('закрытый опрос не кликабелен', async () => {
    render(Polls);
    await waitFor(() => {
      expect(screen.getByText(/кабаре или драма/i)).toBeInTheDocument();
    });
    const closed = screen.getByText('Кабаре').closest('button');
    expect(closed?.disabled).toBe(true);
  });
});

describe('E2E: Участник · Взнос', () => {
  it('показывает сумму долга', async () => {
    render(Fees);
    await waitFor(() => {
      expect(screen.getByText(/ТВОЙ ДОЛГ/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/400/)).toBeInTheDocument();
  });

  it('показывает порог', async () => {
    render(Fees);
    await waitFor(() => {
      expect(screen.getByText(/600/i)).toBeInTheDocument();
    });
  });

  it('форма «Я оплатил» рендерится', async () => {
    render(Fees);
    await waitFor(() => {
      expect(screen.getByText(/Я оплатил/i)).toBeInTheDocument();
    });
    expect(screen.getByLabelText(/Сумма/i)).toBeInTheDocument();
    expect(screen.getByText('Отправить руководителю')).toBeInTheDocument();
  });

  it('отправка формы оплаты показывает подтверждение', async () => {
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
  it('показывает имя пользователя', async () => {
    render(Profile);
    await waitFor(() => {
      expect(screen.getByText(/Аня К\./i)).toBeInTheDocument();
    });
  });

  it('показывает линковку аккаунтов', async () => {
    render(Profile);
    await waitFor(() => {
      expect(screen.getByText(/ВКонтакте/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/Telegram/i)).toBeInTheDocument();
  });

  it('показывает кнопку чата с руководителем', async () => {
    render(Profile);
    await waitFor(() => {
      expect(screen.getByText(/Написать руководителю/i)).toBeInTheDocument();
    });
  });

  it('академ показывает «Включает руководитель»', async () => {
    render(Profile);
    await waitFor(() => {
      expect(screen.getByText(/Включает руководитель/i)).toBeInTheDocument();
    });
  });
});
