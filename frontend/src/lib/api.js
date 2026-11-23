/**
 * API-клиент. Сейчас — mock-данные (совпадают с прототипом).
 * Для подключения к реальному боту: замени fetchMock на fetch
 * и укажи API_BASE.
 */

const API_BASE = '/api'; // при dev — проксируется к 127.0.0.1:8080

// ─── Mock-данные ─────────────────────────────────────────────

const mock = {
  user: {
    id: 1, name: 'Аня К.', role: 'member', // 'member' | 'admin'
    vk_id: 253519572, tg_username: '@anny',
    subscription: 'active', // 'active' | 'paused' | 'guest'
    settings: { announcements: true, akadem: false },
  },

  events: [
    {
      id: 12, title: 'Тренировка по импровизации',
      starts_at: '2026-11-25T19:00', ends_at: '2026-11-25T21:00',
      place: 'Зал №2, корпус 4', note: 'Спарринг-сцены, брать сменку и воду.',
      status: 'active',
      counts: { yes: 7, maybe: 2, no: 3 },
      votes: [
        { name: 'Аня К.', answer: 'yes', tag: null },
        { name: 'Боба', answer: 'yes', tag: 'TG' },
        { name: 'Вика', answer: 'yes', tag: null },
        { name: 'Гоша', answer: 'maybe', tag: null },
        { name: 'Дима', answer: 'no', tag: null },
        { name: 'Ева', answer: 'no', tag: null, prev: 'yes', prevTime: '19:40' },
        { name: 'Женя', answer: 'yes', tag: 'VK' },
        { name: 'Зоя', answer: 'no', tag: 'TG' },
      ],
      my_vote: null,
    },
    {
      id: 13, title: 'Репетиция показа',
      starts_at: '2026-11-28T18:00', ends_at: '2026-11-28T21:00',
      place: 'Актовый зал', note: null, status: 'active',
      counts: { yes: 11, maybe: 1, no: 0 },
      votes: [], my_vote: null,
    },
    {
      id: 14, title: 'Осенний показ',
      starts_at: '2026-12-14T17:00', ends_at: '2026-12-14T20:00',
      place: 'Актовый зал', note: 'Вход свободный', status: 'closed',
      counts: { yes: 4, maybe: 0, no: 0 },
      votes: [], my_vote: null,
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
    monthly: 200, threshold: 600,
    my_debt: 400,
    history: [
      { id: 1, kind: 'accrual', label: 'Взнос за ноябрь', amount: 200, date: '1 ноября' },
      { id: 2, kind: 'payment', label: 'Платёж · наличными', amount: -200, date: '28 октября' },
      { id: 3, kind: 'accrual', label: 'Взнос за октябрь', amount: 200, date: '1 октября' },
      { id: 4, kind: 'payment', label: 'Платёж · перевод', amount: -200, date: '30 сентября' },
    ],
  },

  // ─── админские ───
  admin: {
    stats: {
      active_events: 3, active_polls: 1,
      subscribers: 24, total_debt: 2400,
      debt_over_threshold: 2, collected_month: 3800,
    },
    applications: [
      { id: 1, name: 'Марк', username: '@mark_kpi', time: '14:02', status: 'pending' },
      { id: 2, name: 'Лиза', username: '@liza_t', time: 'вчера', status: 'pending' },
      { id: 3, name: 'Костя', username: '@kv', time: '12 ноя', status: 'approved' },
    ],
    fee_reports: [
      { id: 1, name: 'Аня К.', amount: 200, method: 'Перевод', time: '13:50', status: 'pending' },
      { id: 2, name: 'Ева', amount: 400, method: 'Наличные', time: '12:15', status: 'pending' },
    ],
    people: [
      { id: 1, name: 'Аня К.', vk: true, tg: '@anny', status: 'active', debt: 400, akadem: false },
      { id: 2, name: 'Боба', vk: false, tg: '@boba', status: 'active', debt: 800, akadem: false },
      { id: 3, name: 'Вика', vk: true, tg: null, status: 'paused', debt: 200, akadem: true },
      { id: 4, name: 'Гоша', vk: true, tg: '@gosh', status: 'active', debt: 0, akadem: false },
      { id: 5, name: 'Дима', vk: true, tg: null, status: 'banned', debt: 600, akadem: false },
    ],
    debts: [
      { name: 'Боба', amount: 800, over: true, last: '28 окт · 200 ₽' },
      { name: 'Аня К.', amount: 400, over: false, last: '28 окт · 200 ₽' },
      { name: 'Дима', amount: 600, over: true, last: '30 сен · 200 ₽' },
      { name: 'Вика', amount: 200, over: false, last: '5 ноя · 200 ₽' },
      { name: 'Ева', amount: 200, over: false, last: '1 ноя · 400 ₽' },
    ],
  },
};

// ─── API интерфейс ───────────────────────────────────────────
// Для реального API: замени тело каждой функции на fetch(API_BASE + path)

export const api = {
  // ── участник ──
  async getEvents() { return [...mock.events]; },
  async getEvent(id) { return mock.events.find(e => e.id === +id); },
  async vote(eventId, answer) {
    const ev = mock.events.find(e => e.id === eventId);
    if (ev) {
      if (ev.my_vote) ev.counts[ev.my_vote]--;
      if (ev.my_vote === answer) { ev.my_vote = null; }
      else { ev.counts[answer]++; ev.my_vote = answer; }
    }
    return ev;
  },
  async getPolls() { return [...mock.polls]; },
  async pollVote(pollId, optionId) {
    const p = mock.polls.find(x => x.id === pollId);
    if (!p || p.status !== 'open') return p;
    const opt = p.options.find(o => o.id === optionId);
    if (!opt) return p;
    const idx = p.my_picks.indexOf(optionId);
    if (idx >= 0) { p.my_picks.splice(idx, 1); opt.count--; p.voted--; }
    else { p.my_picks.push(optionId); opt.count++; p.voted++; }
    return p;
  },
  async getFees() { return { ...mock.fees }; },
  async reportPayment(amount, method) {
    mock.admin.fee_reports.push({ id: Date.now(), name: mock.user.name, amount, method, time: 'сейчас', status: 'pending' });
    return { ok: true };
  },
  async getProfile() { return { ...mock.user }; },
  async sendMessage(text) { return { ok: true }; },
  async getMessages() {
    return [
      { id: 1, from: 'them', text: 'Привет! Когда следующий показ?', time: '14:02' },
      { id: 2, from: 'me', text: '14 декабря', time: '14:05' },
    ];
  },

  // ── админ ──
  async getAdminStats() { return { ...mock.admin.stats }; },
  async getApplications() { return [...mock.admin.applications]; },
  async approveApplication(id, approve) {
    const a = mock.admin.applications.find(x => x.id === id);
    if (a) a.status = approve ? 'approved' : 'denied';
    return a;
  },
  async getFeeReports() { return [...mock.admin.fee_reports]; },
  async confirmFeeReport(id, approve, amount) {
    const r = mock.admin.fee_reports.find(x => x.id === id);
    if (r) {
      r.status = approve ? 'confirmed' : 'rejected';
      if (approve && amount) r.amount = amount;
      if (approve) {
        const d = mock.admin.debts.find(x => x.name === r.name);
        if (d) { d.amount = Math.max(0, d.amount - r.amount); }
        mock.admin.stats.total_debt -= r.amount;
      }
    }
    return r;
  },
  async getPeople() { return [...mock.admin.people]; },
  async toggleAkadem(personId, on) {
    const p = mock.admin.people.find(x => x.id === personId);
    if (p) p.akadem = on;
    return p;
  },
  async recordPayment(who, amount, what) {
    const d = mock.admin.debts.find(x => x.name === who);
    if (d) { d.amount = Math.max(0, d.amount - amount); mock.admin.stats.total_debt -= amount; }
    return { ok: true };
  },
  async recordCharge(who, amount, what) {
    const d = mock.admin.debts.find(x => x.name === who);
    if (d) d.amount += amount;
    else mock.admin.debts.push({ name: who, amount, over: amount > 600, last: what });
    mock.admin.stats.total_debt += amount;
    return { ok: true };
  },
  async createEvent(data) {
    mock.events.unshift({
      id: Date.now(), ...data, status: 'active',
      counts: { yes: 0, maybe: 0, no: 0 }, votes: [], my_vote: null,
    });
    return { ok: true };
  },
};
