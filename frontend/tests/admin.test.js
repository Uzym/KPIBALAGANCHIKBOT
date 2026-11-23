/** E2E: руководитель — дашборд, события, люди, оплата. */
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/svelte';

import Dashboard from '../src/pages/admin/Dashboard.svelte';
import Events from '../src/pages/admin/Events.svelte';
import People from '../src/pages/admin/People.svelte';
import Fees from '../src/pages/admin/Fees.svelte';

describe('E2E: Админ · Дашборд', () => {
  it('показывает счётчики', async () => {
    render(Dashboard);
    await waitFor(() => {
      expect(screen.getByText(/СобЫТИЙ|Событий/i, { exact: false })).toBeInTheDocument();
    });
  });

  it('показывает заявки Telegram', async () => {
    render(Dashboard);
    await waitFor(() => {
      expect(screen.getByText(/Марк/i)).toBeInTheDocument();
    });
  });

  it('показывает подтверждения платежей', async () => {
    render(Dashboard);
    await waitFor(() => {
      expect(screen.getByText(/Подтвердить оплату/i)).toBeInTheDocument();
    });
  });

  it('кнопка «Подтвердить» уменьшает количество карточек', async () => {
    render(Dashboard);
    await waitFor(() => screen.getAllByText('Подтвердить').length >= 1);

    const before = screen.getAllByText('Подтвердить').length;
    const btn = screen.getAllByText('Подтвердить')[0].closest('button');
    fireEvent.click(btn);
    await waitFor(() => {
      const after = screen.queryAllByText('Подтвердить').length;
      expect(after).toBeLessThan(before);
    }, { timeout: 3000 });
  });

  it('кнопка «Принять» в заявках работает', async () => {
    render(Dashboard);
    await waitFor(() => screen.getByText(/Марк/i));

    const approveBtns = screen.queryAllByRole('button', { name: /Принять/ });
    if (approveBtns.length > 0) {
      fireEvent.click(approveBtns[0]);
      await waitFor(() => {
        expect(screen.getByText(/Принят/i)).toBeInTheDocument();
      });
    }
  });

  it('баннер ошибки отображается', async () => {
    render(Dashboard);
    await waitFor(() => {
      expect(screen.getByText(/не доставлены/i)).toBeInTheDocument();
    });
  });
});

describe('E2E: Админ · События', () => {
  it('показывает таблицу событий', async () => {
    render(Events);
    await waitFor(() => {
      expect(screen.getByText(/Тренировка по импровизации/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/Репетиция показа/i)).toBeInTheDocument();
  });

  it('показывает статусы', async () => {
    render(Events);
    await waitFor(() => {
      const statuses = screen.getAllByText(/Идёт запись/i);
      expect(statuses.length).toBeGreaterThanOrEqual(1);
    });
    expect(screen.getAllByText(/Запись закрыта|Закрыта/i).length).toBeGreaterThanOrEqual(1);
  });

  it('форма создания раскрывается', async () => {
    render(Events);
    await waitFor(() => screen.getByText('Создать'));

    fireEvent.click(screen.getByText('Создать'));
    await waitFor(() => {
      expect(screen.getByLabelText(/Название/i)).toBeInTheDocument();
    });
  });

  it('создание события добавляет строку', async () => {
    render(Events);
    await waitFor(() => screen.getByText('Создать'));
    fireEvent.click(screen.getByText('Создать'));
    await waitFor(() => screen.getByLabelText(/Название/i));

    fireEvent.input(screen.getByLabelText(/Название/i), {
      target: { value: 'Новое событие' },
    });
    fireEvent.click(screen.getByText('Опубликовать'));
    await waitFor(() => {
      expect(screen.getByText(/Новое событие/i)).toBeInTheDocument();
    });
  });
});

describe('E2E: Админ · Люди', () => {
  it('показывает список людей', async () => {
    render(People);
    await waitFor(() => {
      expect(screen.getByText(/Аня К\./i)).toBeInTheDocument();
    });
    expect(screen.getByText(/Боба/i)).toBeInTheDocument();
    expect(screen.getByText(/Вика/i)).toBeInTheDocument();
  });

  it('показывает долги', async () => {
    render(People);
    await waitFor(() => screen.getByText(/Боба/i));
    expect(screen.getByText(/800/i)).toBeInTheDocument();
  });

  it('тумблер академа переключается', async () => {
    render(People);
    await waitFor(() => screen.getAllByRole('switch'));

    const toggles = screen.getAllByRole('switch');
    expect(toggles.length).toBeGreaterThanOrEqual(3);

    const first = toggles[0];
    const before = first.getAttribute('aria-checked');
    fireEvent.click(first);
    await waitFor(() => {
      const after = first.getAttribute('aria-checked');
      expect(after).not.toBe(before);
    });
  });

  it('поиск фильтрует людей', async () => {
    render(People);
    await waitFor(() => screen.getByText(/Аня К\./i));

    const search = screen.getByPlaceholderText(/Поиск/i);
    fireEvent.input(search, { target: { value: 'Боба' } });
    await waitFor(() => {
      expect(screen.getByText(/Боба/i)).toBeInTheDocument();
      expect(screen.queryByText(/Аня К\./i)).not.toBeInTheDocument();
    });
  });
});

describe('E2E: Админ · Оплата', () => {
  it('показывает статы', async () => {
    render(Fees);
    await waitFor(() => {
      expect(screen.getByText(/Собрано/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/Долг/i)).toBeInTheDocument();
    expect(screen.getByText(/Выше порога/i)).toBeInTheDocument();
  });

  it('переключатель Платёж/Доп.трата', async () => {
    render(Fees);
    await waitFor(() => screen.getByText('Платёж'));
    expect(screen.getByText('Доп. трата')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Доп. трата'));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Начислить трату/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Платёж'));
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Записать платёж/i })).toBeInTheDocument();
    });
  });

  it('форма платежа рендерится', async () => {
    render(Fees);
    await waitFor(() => screen.getByLabelText(/Кто/i));
    expect(screen.getByLabelText(/Сумма/i)).toBeInTheDocument();
  });

  it('отправка платежа очищает форму', async () => {
    render(Fees);
    await waitFor(() => screen.getByLabelText(/Кто/i));

    fireEvent.input(screen.getByLabelText(/Кто/i), { target: { value: 'Аня К.' } });
    fireEvent.input(screen.getByLabelText(/Сумма/i), { target: { value: '100' } });
    fireEvent.click(screen.getByRole('button', { name: /Записать платёж/i }));
    await waitFor(() => {
      expect(screen.getByLabelText(/Кто/i).value).toBe('');
    });
  });

  it('показывает список должников', async () => {
    render(Fees);
    await waitFor(() => screen.getByText(/Должники/i));
    expect(screen.getByText(/Боба/i)).toBeInTheDocument();
  });
});
