/** Тесты API-клиента: mock-данные корректны, мутации работают. */
import { describe, it, expect } from 'vitest';
import { api } from '../src/lib/api.js';

describe('API mock: события', () => {
  it('возвращает список событий', async () => {
    const events = await api.getEvents();
    expect(events.length).toBeGreaterThanOrEqual(3);
    expect(events[0].title).toBeTruthy();
    expect(events[0].counts).toHaveProperty('yes');
    expect(events[0].counts).toHaveProperty('maybe');
    expect(events[0].counts).toHaveProperty('no');
  });

  it('возвращает событие по id', async () => {
    const ev = await api.getEvent(12);
    expect(ev).toBeTruthy();
    expect(ev.title).toContain('Тренировка');
  });

  it('голосование увеличивает счётчик', async () => {
    const before = await api.getEvent(12);
    const yesBefore = before.counts.yes;

    const after = await api.vote(12, 'yes');
    expect(after.counts.yes).toBe(yesBefore + 1);
    expect(after.my_vote).toBe('yes');
  });

  it('повторный голос того же ответа снимает его', async () => {
    const ev = await api.getEvent(12);
    // если ещё не проголосировали — голосуем
    if (!ev.my_vote) await api.vote(12, 'yes');
    const before = await api.getEvent(12);
    const yesBefore = before.counts.yes;

    const after = await api.vote(12, 'yes'); // повтор = снять
    expect(after.counts.yes).toBe(yesBefore - 1);
    expect(after.my_vote).toBeNull();
  });

  it('смена ответа: минус старый, плюс новый', async () => {
    // event 13 — не тронут предыдущими тестами
    await api.vote(13, 'yes');
    const before = await api.getEvent(13);
    const yesBefore = before.counts.yes; // примитив — не мутирует
    const noBefore = before.counts.no;

    const after = await api.vote(13, 'no');
    expect(after.counts.yes).toBe(yesBefore - 1);
    expect(after.counts.no).toBe(noBefore + 1);
    expect(after.my_vote).toBe('no');
    // cleanup: снять 'no'
    await api.vote(13, 'no');
  });
});

describe('API mock: опросы', () => {
  it('возвращает опросы', async () => {
    const polls = await api.getPolls();
    expect(polls.length).toBeGreaterThanOrEqual(2);
    expect(polls[0].options.length).toBeGreaterThanOrEqual(2);
  });

  it('голосование в опросе обновляет счётчик', async () => {
    const polls = await api.getPolls();
    const open = polls.find(p => p.status === 'open');
    expect(open).toBeTruthy();

    const optBefore = open.options[0].count;
    const updated = await api.pollVote(open.id, open.options[0].id);
    expect(updated.options[0].count).toBe(optBefore + 1);
    expect(updated.my_picks).toContain(open.options[0].id);
  });

  it('повторное голосование снимает выбор', async () => {
    const polls = await api.getPolls();
    const open = polls.find(p => p.status === 'open');
    if (!open.my_picks.includes(open.options[0].id)) {
      await api.pollVote(open.id, open.options[0].id);
    }
    const before = (await api.getPolls()).find(p => p.id === open.id);
    const countBefore = before.options[0].count;

    const after = await api.pollVote(open.id, open.options[0].id); // toggle
    expect(after.options[0].count).toBe(countBefore - 1);
    expect(after.my_picks).not.toContain(open.options[0].id);
  });
});

describe('API mock: оплата (участник)', () => {
  it('возвращает долг и историю', async () => {
    const fees = await api.getFees();
    expect(fees.my_debt).toBeGreaterThanOrEqual(0);
    expect(fees.history.length).toBeGreaterThan(0);
    expect(fees.monthly).toBe(200);
    expect(fees.threshold).toBe(600);
  });

  it('отчёт о платеже создаёт заявку', async () => {
    const before = await api.getFeeReports();
    const pendingBefore = before.filter(r => r.status === 'pending').length;

    await api.reportPayment(200, 'Перевод');
    const after = await api.getFeeReports();
    const pendingAfter = after.filter(r => r.status === 'pending').length;
    expect(pendingAfter).toBe(pendingBefore + 1);
  });
});

describe('API mock: админ', () => {
  it('возвращает статистику', async () => {
    const stats = await api.getAdminStats();
    expect(stats.active_events).toBeGreaterThan(0);
    expect(stats.subscribers).toBeGreaterThan(0);
    expect(stats.total_debt).toBeGreaterThanOrEqual(0);
  });

  it('возвращает заявки', async () => {
    const apps = await api.getApplications();
    expect(apps.length).toBeGreaterThan(0);
    expect(apps.some(a => a.status === 'pending')).toBe(true);
  });

  it('одобрение заявки меняет статус', async () => {
    const apps = await api.getApplications();
    const pending = apps.find(a => a.status === 'pending');
    expect(pending).toBeTruthy();

    const updated = await api.approveApplication(pending.id, true);
    expect(updated.status).toBe('approved');
  });

  it('подтверждение платежа уменьшает долг', async () => {
    const statsBefore = await api.getAdminStats();
    const reports = await api.getFeeReports();
    const pending = reports.find(r => r.status === 'pending');
    if (pending) {
      await api.confirmFeeReport(pending.id, true, pending.amount);
      const statsAfter = await api.getAdminStats();
      expect(statsAfter.total_debt).toBeLessThan(statsBefore.total_debt);
    }
  });

  it('возвращает людей', async () => {
    const people = await api.getPeople();
    expect(people.length).toBeGreaterThanOrEqual(3);
    expect(people.some(p => p.akadem === true)).toBe(true);
  });

  it('тумблер академа переключается', async () => {
    const people = await api.getPeople();
    const target = people.find(p => !p.akadem);
    if (target) {
      const updated = await api.toggleAkadem(target.id, true);
      expect(updated.akadem).toBe(true);
    }
  });

  it('платёж уменьшает общий долг', async () => {
    const before = await api.getAdminStats();
    await api.recordPayment('Аня К.', 100, 'тест');
    const after = await api.getAdminStats();
    expect(after.total_debt).toBeLessThan(before.total_debt);
  });

  it('доп. трата увеличивает общий долг', async () => {
    const before = await api.getAdminStats();
    await api.recordCharge('Аня К.', 50, 'тест трата');
    const after = await api.getAdminStats();
    expect(after.total_debt).toBeGreaterThan(before.total_debt);
  });
});

describe('API mock: профиль и чат', () => {
  it('возвращает профиль', async () => {
    const p = await api.getProfile();
    expect(p.name).toBeTruthy();
    expect(p.role).toBeTruthy();
  });

  it('возвращает массив сообщений (может быть пустым)', async () => {
    const msgs = await api.getMessages();
    expect(Array.isArray(msgs)).toBe(true);
  });

  it('отправка сообщения возвращает ok', async () => {
    const result = await api.sendMessage('тест');
    expect(result.ok).toBe(true);
  });
});
