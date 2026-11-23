/**
 * API-клиент: реальный API (aiohttp :8080) → mock fallback для dev/tests.
 */

const API_BASE = '/api';

async function tryFetch(path, options = {}) {
  try {
    const resp = await fetch(`${API_BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    if (!resp.ok) return null;
    return await resp.json();
  } catch {
    return null;
  }
}

async function apiPost(path, body) { return tryFetch(path, { method: 'POST', body: JSON.stringify(body) }); }
async function apiPut(path, body) { return tryFetch(path, { method: 'PUT', body: JSON.stringify(body) }); }
async function apiDelete(path) { return tryFetch(path, { method: 'DELETE' }); }

// ─── Mock ────────────────────────────────────────────────────

const mock = {
  user: { id: 1, name: 'Аня К.', role: 'member', subscription: 'active' },
  events: [
    {
      id: 12, title: 'Тренировка по импровизации',
      starts_at: '2026-11-25T19:00', ends_at: '2026-11-25T21:00',
      place: 'Зал №2, корпус 4', note: 'Спарринг-сцены', status: 'active',
      counts: { yes: 7, maybe: 2, no: 3 },
      votes: [
        { name: 'Аня К.', answer: 'yes', tag: null },
        { name: 'Боба', answer: 'yes', tag: 'TG' },
        { name: 'Вика', answer: 'yes', tag: null },
        { name: 'Гоша', answer: 'maybe', tag: null },
        { name: 'Дима', answer: 'no', tag: null },
        { name: 'Ева', answer: 'no', tag: null, prev: 'yes', prevTime: '19:40' },
      ],
      my_vote: null, announcements: [],
    },
    {
      id: 13, title: 'Репетиция показа',
      starts_at: '2026-11-28T18:00', ends_at: '2026-11-28T21:00',
      place: 'Актовый зал', note: null, status: 'active',
      counts: { yes: 11, maybe: 1, no: 0 }, votes: [], my_vote: null, announcements: [],
    },
    {
      id: 14, title: 'Осенний показ',
      starts_at: '2026-12-14T17:00', ends_at: '2026-12-14T20:00',
      place: 'Актовый зал', note: 'Вход свободный', status: 'closed',
      counts: { yes: 4, maybe: 0, no: 0 }, votes: [], my_vote: null, announcements: [],
    },
  ],
  polls: [
    {
      id: 1, question: 'Куда едем в декабре?', multi: true,
      status: 'open', deadline: '28 ноября', voted: 8,
      options: [
        { id: 1, label: 'Баня', count: 5 },
        { id: 2, label: 'Каток', count: 3 },
        { id: 3, label: 'Квартирник', count: 4 },
      ],
      my_picks: [],
    },
    {
      id: 2, question: 'Финал сезона: кабаре или драма?', multi: false,
      status: 'closed', deadline: '15 ноября', voted: 16,
      options: [
        { id: 1, label: 'Кабаре', count: 12 },
        { id: 2, label: 'Драма', count: 4 },
      ],
      my_picks: [],
    },
  ],
  fees: {
    monthly: 200, threshold: 600, my_debt: 400,
    history: [
      { id: 1, kind: 'accrual', label: 'Взнос за ноябрь', amount: 200, date: '1 ноября' },
      { id: 2, kind: 'payment', label: 'Платёж · наличными', amount: -200, date: '28 октября' },
    ],
  },
  admin: {
    stats: { active_events: 3, active_polls: 1, subscribers: 24, total_debt: 2400, collected_month: 3800 },
    applications: [
      { id: 1, name: 'Марк', username: '@mark_kpi', time: '14:02', status: 'pending' },
      { id: 2, name: 'Лиза', username: '@liza_t', time: 'вчера', status: 'pending' },
    ],
    fee_reports: [
      { id: 1, name: 'Аня К.', amount: 200, method: 'Перевод', time: '13:50', status: 'pending' },
    ],
    debts: [
      { name: 'Боба', amount: 800 }, { name: 'Аня К.', amount: 400 },
      { name: 'Дима', amount: 600 }, { name: 'Вика', amount: 200 }, { name: 'Ева', amount: 200 },
    ],
    people: [
      { id: 1, name: 'Аня К.', vk: true, tg: '@anny', status: 'active', debt: 400, akadem: false },
      { id: 2, name: 'Боба', vk: false, tg: '@boba', status: 'active', debt: 800, akadem: false },
      { id: 3, name: 'Вика', vk: true, tg: null, status: 'paused', debt: 200, akadem: true },
      { id: 4, name: 'Гоша', vk: true, tg: '@gosh', status: 'active', debt: 0, akadem: false },
      { id: 5, name: 'Дима', vk: true, tg: null, status: 'banned', debt: 600, akadem: false },
    ],
  },
};

// ─── API ─────────────────────────────────────────────────────

export const api = {
  // ══ СОБЫТИЯ: чтение ══

  async getEvents() {
    const real = await tryFetch('/events');
    return Array.isArray(real) ? real : [...mock.events];
  },

  async getEvent(id) {
    const real = await tryFetch(`/events/${id}`);
    return real ?? mock.events.find(e => e.id === +id);
  },

  // ══ СОБЫТИЯ: запись ══

  async createEvent(data) {
    const real = await apiPost('/events', data);
    if (real) return real;
    mock.events.unshift({ id: Date.now(), ...data, status: 'active',
      counts: { yes: 0, maybe: 0, no: 0 }, votes: [], my_vote: null, announcements: [] });
    return { ok: true };
  },

  async updateEvent(id, data) {
    const real = await apiPut(`/events/${id}`, data);
    if (real) return real;
    const ev = mock.events.find(e => e.id === id);
    if (ev) Object.assign(ev, data);
    return ev;
  },

  async deleteEvent(id) {
    const real = await apiDelete(`/events/${id}`);
    mock.events = mock.events.filter(e => e.id !== id);
    return real ?? { ok: true };
  },

  async closeEvent(id) {
    const real = await apiPost(`/events/${id}/close`);
    if (real) return real;
    const ev = mock.events.find(e => e.id === id);
    if (ev) ev.status = 'closed';
    return { ok: true };
  },

  async reopenEvent(id) {
    const real = await apiPost(`/events/${id}/reopen`);
    if (real) return real;
    const ev = mock.events.find(e => e.id === id);
    if (ev) ev.status = 'active';
    return { ok: true };
  },

  async cancelEvent(id) {
    const real = await apiPost(`/events/${id}/cancel`);
    if (real) return real;
    const ev = mock.events.find(e => e.id === id);
    if (ev) { ev.status = 'cancelled'; ev.cancelled = true; }
    return { ok: true };
  },

  async announceEvent(id, text) {
    const real = await apiPost(`/events/${id}/announce`, { text });
    if (real) return real;
    const ev = mock.events.find(e => e.id === id);
    if (ev) { if (!ev.announcements) ev.announcements = [];
      ev.announcements.unshift({ text, time: 'сейчас' }); }
    return { ok: true };
  },

  async vote(eventId, answer) {
    const real = await apiPost(`/events/${eventId}/vote`, { answer, platform: 'web', user_id: 1 });
    if (real) return real;
    const ev = mock.events.find(e => e.id === eventId);
    if (ev) {
      if (ev.my_vote) ev.counts[ev.my_vote]--;
      if (ev.my_vote === answer) ev.my_vote = null;
      else { ev.counts[answer]++; ev.my_vote = answer; }
    }
    return ev;
  },

  // ══ ОПРОСЫ: чтение ══

  async getPolls() {
    const real = await tryFetch('/polls');
    return Array.isArray(real) ? real : [...mock.polls];
  },

  // ══ ОПРОСЫ: запись ══

  async createPoll(data) {
    const real = await apiPost('/polls', data);
    if (real) return real;
    mock.polls.unshift({
      id: Date.now(), question: data.question, multi: data.multichoice,
      status: 'open', deadline: null, voted: 0,
      options: data.options.map((label, i) => ({ id: i, label, count: 0 })),
      my_picks: [],
    });
    return { ok: true };
  },

  async updatePoll(id, data) {
    const real = await apiPut(`/polls/${id}`, data);
    if (real) return real;
    const p = mock.polls.find(x => x.id === id);
    if (p) {
      if (data.question) p.question = data.question;
      if (data.multichoice !== undefined) p.multi = data.multichoice;
      if (data.options) p.options = data.options.map((label, i) =>
        ({ id: p.options[i]?.id ?? i, label, count: p.options[i]?.count ?? 0 }));
    }
    return p;
  },

  async deletePoll(id) {
    const real = await apiDelete(`/polls/${id}`);
    mock.polls = mock.polls.filter(p => p.id !== id);
    return real ?? { ok: true };
  },

  async closePoll(id) {
    const real = await apiPost(`/polls/${id}/close`);
    if (real) return real;
    const p = mock.polls.find(x => x.id === id);
    if (p) p.status = 'closed';
    return { ok: true };
  },

  async reopenPoll(id) {
    const real = await apiPost(`/polls/${id}/reopen`);
    if (real) return real;
    const p = mock.polls.find(x => x.id === id);
    if (p) p.status = 'open';
    return { ok: true };
  },

  async pollVote(pollId, optionId) {
    const real = await apiPost(`/polls/${pollId}/vote`, { option_id: optionId });
    if (real) return real;
    const p = mock.polls.find(x => x.id === pollId);
    if (!p || p.status !== 'open') return p;
    const opt = p.options.find(o => o.id === optionId);
    if (!opt) return p;
    const idx = p.my_picks.indexOf(optionId);
    if (idx >= 0) { p.my_picks.splice(idx, 1); opt.count--; p.voted--; }
    else { p.my_picks.push(optionId); opt.count++; p.voted++; }
    return p;
  },

  // ══ ОПЛАТА (участник) ══

  async getFees() {
    const real = await tryFetch('/fees?person_id=1');
    if (real && real.my_debt !== undefined) return real;
    return { ...mock.fees };
  },

  async reportPayment(amount, method) {
    const real = await apiPost('/fees/report', { amount, method });
    if (real) return real;
    mock.admin.fee_reports.push({ id: Date.now(), name: mock.user.name, amount, method, time: 'сейчас', status: 'pending' });
    return { ok: true };
  },

  // ══ ПРОФИЛЬ / ЧАТ ══

  async getProfile() { return { ...mock.user }; },
  async sendMessage(text) { return { ok: true }; },
  async getMessages() { return []; },

  // ══ АДМИН ══

  async getAdminStats() {
    const real = await tryFetch('/admin/stats');
    if (real && real.active_events !== undefined) return real;
    return { ...mock.admin.stats };
  },

  async getApplications() {
    const real = await tryFetch('/admin/applications');
    return Array.isArray(real) ? real : [...mock.admin.applications];
  },

  async approveApplication(id, approve) {
    const a = mock.admin.applications.find(x => x.id === id);
    if (a) a.status = approve ? 'approved' : 'denied';
    return a;
  },

  async getFeeReports() {
    return [...mock.admin.fee_reports];
  },

  async confirmFeeReport(id, approve, amount) {
    const r = mock.admin.fee_reports.find(x => x.id === id);
    if (r) {
      r.status = approve ? 'confirmed' : 'rejected';
      if (approve && amount) r.amount = parseInt(amount) || r.amount;
      if (approve) {
        const d = mock.admin.debts.find(x => x.name === r.name);
        if (d) d.amount = Math.max(0, d.amount - r.amount);
        mock.admin.stats.total_debt = mock.admin.debts.reduce((s, x) => s + x.amount, 0);
      }
    }
    return r;
  },

  async getPeople() {
    const real = await tryFetch('/admin/people');
    return Array.isArray(real) ? real : [...mock.admin.people];
  },

  async getPersonFees(personId) {
    const real = await tryFetch(`/admin/people/${personId}/fees`);
    return real;
  },

  async getPersonAttendance(personId) {
    const real = await tryFetch(`/admin/people/${personId}/attendance`);
    return Array.isArray(real) ? real : [];
  },

  async toggleAkadem(personId, on) {
    const p = mock.admin.people.find(x => x.id === personId);
    if (p) p.akadem = on;
    return p;
  },

  async recordPayment(personName, amount, label, personId) {
    const a = parseInt(amount) || 0;
    const real = await apiPost('/admin/fees/payment', { person_id: personId || 1, amount: a, label });
    if (real) return real;
    const d = mock.admin.debts.find(x => x.name === personName);
    if (d) d.amount = Math.max(0, d.amount - a);
    mock.admin.stats.total_debt = mock.admin.debts.reduce((s, x) => s + x.amount, 0);
    return { ok: true };
  },

  async recordCharge(personName, amount, label, personId) {
    const a = parseInt(amount) || 0;
    const real = await apiPost('/admin/fees/charge', { person_id: personId || 1, amount: a, label });
    if (real) return real;
    const d = mock.admin.debts.find(x => x.name === personName);
    if (d) d.amount += a;
    else mock.admin.debts.push({ name: personName, amount: a });
    mock.admin.stats.total_debt = mock.admin.debts.reduce((s, x) => s + x.amount, 0);
    return { ok: true };
  },
};
