<script>
  import AdminShell from '../../components/AdminShell.svelte';
  import { api } from '../../lib/api.js';

  let stats = null;
  let applications = [];
  let feeReports = [];
  let loading = true;

  async function load() {
    [stats, applications, feeReports] = await Promise.all([
      api.getAdminStats(), api.getApplications(), api.getFeeReports(),
    ]);
    loading = false;
  }
  load();

  async function approveApp(id, ok) {
    await api.approveApplication(id, ok);
    applications = [...applications];
  }

  async function confirmPay(id, ok) {
    const input = document.getElementById(`conf-${id}`);
    const amount = input ? parseInt(input.value) : undefined;
    await api.confirmFeeReport(id, ok, amount);
    feeReports = [...feeReports];
    stats = await api.getAdminStats();
  }
</script>

<AdminShell title="Дашборд">
  {#if loading}
    <div class="skeleton" style="height:300px;border-radius:18px;"></div>
  {:else}
    <!-- ошибка -->
    <div class="error-banner" role="alert">
      <svg class="ic" viewBox="0 0 24 24"><path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/></svg>
      <span>2 карточки не доставлены — получатели заблокировали бота.</span>
    </div>

    <!-- счётчики -->
    <div class="stat-grid">
      <div class="stat-card">
        <div class="label">Событий</div>
        <div class="value">{stats.active_events}</div>
        <div class="sub">ближайшее — вт 19:00</div>
      </div>
      <div class="stat-card">
        <div class="label">Подписчики</div>
        <div class="value">{stats.subscribers}</div>
        <div class="sub">2 академ · 1 бан</div>
      </div>
      <div class="stat-card">
        <div class="label">Долг</div>
        <div class="value warn">{stats.total_debt} ₽</div>
        <div class="sub">у {stats.debt_over_threshold + 3} человек</div>
      </div>
      <div class="stat-card">
        <div class="label">Собрано</div>
        <div class="value">{stats.collected_month} ₽</div>
        <div class="sub">в ноябре</div>
      </div>
    </div>

    <!-- подтверждения платежей -->
    <div class="card" style="margin-bottom:20px;">
      <div class="row-between" style="margin-bottom:12px;">
        <p class="eyebrow" style="margin:0;">Подтвердить оплату</p>
        <span class="tag status-warn">{feeReports.filter(r => r.status === 'pending').length} ждут</span>
      </div>
      {#each feeReports.filter(r => r.status === 'pending') as r (r.id)}
        <div class="confirm-card">
          <div style="margin-bottom:8px;">
            <span class="who">{r.name}</span>
            <span class="meta" style="margin-left:8px;">{r.method} · {r.time}</span>
          </div>
          <div class="confirm-actions">
            <div class="confirm-input-row">
              <input class="amount-edit" type="number" min="1" step="1" id="conf-{r.id}" value={r.amount}
                     aria-label="Сумма от {r.name}">
              <span class="meta">₽</span>
            </div>
            <div class="confirm-btn-row">
              <button class="btn btn-primary btn-sm confirm-btn" onclick={() => confirmPay(r.id, true)}>Подтвердить</button>
              <button class="btn btn-secondary btn-sm confirm-btn" onclick={() => confirmPay(r.id, false)}>Отклонить</button>
            </div>
          </div>
        </div>
      {:else}
        <p class="meta" style="text-align:center;padding:12px;">Нет ожидающих</p>
      {/each}
    </div>

    <!-- заявки TG -->
    <div class="card" style="margin-bottom:20px;">
      <div class="row-between" style="margin-bottom:12px;">
        <p class="eyebrow" style="margin:0;">Заявки Telegram</p>
        <span class="tag status-open">{applications.filter(a => a.status === 'pending').length} новых</span>
      </div>
      {#each applications.filter(a => a.status === 'pending') as app (app.id)}
        <div class="list-row" style="grid-template-columns:1fr auto;">
          <div class="body">
            <div class="title">{app.name} <span class="meta" style="font-size:11px;">{app.username}</span></div>
            <div class="sub">{app.time}</div>
          </div>
          <div class="row" style="gap:6px;">
            <button class="btn btn-primary btn-sm" onclick={() => approveApp(app.id, true)} aria-label="Принять {app.name}">
              <svg class="ic-sm" viewBox="0 0 24 24"><path d="M20 6L9 17l-5-5"/></svg>
            </button>
            <button class="btn btn-secondary btn-sm" onclick={() => approveApp(app.id, false)} aria-label="Отказать {app.name}">
              <svg class="ic-sm" viewBox="0 0 24 24"><path d="M18 6L6 18M6 6l12 12"/></svg>
            </button>
          </div>
        </div>
      {/each}
      {#each applications.filter(a => a.status !== 'pending') as app (app.id)}
        <div class="list-row" style="grid-template-columns:1fr auto;opacity:0.55;">
          <div class="body"><div class="title">{app.name}</div></div>
          <span class="tag" class:status-open={app.status === 'approved'} class:status-warn={app.status === 'denied'}>
            {app.status === 'approved' ? 'Принят' : 'Отказ'}
          </span>
        </div>
      {/each}
    </div>
  {/if}
</AdminShell>

<style>
  .ic { width:20px; height:20px; stroke:currentColor; fill:none; stroke-width:1.7; stroke-linecap:round; stroke-linejoin:round; flex-shrink:0; color:var(--danger); }
  .ic-sm { width:16px; height:16px; stroke:currentColor; fill:none; stroke-width:1.7; stroke-linecap:round; stroke-linejoin:round; }
  .who { font-weight:600; font-size:14px; }
  .amount-edit {
    width:80px; padding:4px 8px; border:1px solid var(--border); border-radius:6px;
    font-family:var(--font-mono); font-size:14px; background:var(--surface); color:var(--fg);
  }
  .confirm-card {
    border:1px solid var(--mustard); border-radius:var(--radius);
    padding:12px 14px; margin-bottom:8px; background:rgba(233,185,74,0.06);
  }
  .confirm-actions {
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  }
  .confirm-input-row { display: flex; align-items: center; gap: 4px; }
  .confirm-btn-row { display: flex; gap: 8px; flex: 1; min-width: 0; }
  .confirm-btn { flex: 1; min-width: 0; }
  @media (max-width: 600px) {
    .confirm-actions { flex-direction: column; align-items: stretch; }
    .confirm-input-row { width: 100%; }
    .confirm-input-row .amount-edit { width: 100%; flex: 1; }
    .confirm-btn-row { width: 100%; }
  }
  @media (max-width: 480px) {
    .confirm-actions { flex-direction: column; align-items: stretch; }
    .confirm-actions .amount-edit { width: 100%; }
    .confirm-actions .btn { flex: 1; }
  }
</style>
