<script>
  import AdminShell from '../../components/AdminShell.svelte';
  import { api } from '../../lib/api.js';

  let stats = null;
  let debts = [];
  let allPeople = [];
  let loading = true;
  let payType = 'pay';
  let formData = { whoId: '', amount: 200, what: '' };

  async function load() {
    stats = await api.getAdminStats();
    allPeople = await api.getPeople();
    debts = allPeople.filter(p => p.debt > 0);
    loading = false;
  }
  load();

  async function submit(e) {
    e.preventDefault();
    if (!formData.whoId || !formData.amount) return;
    const person = allPeople.find(p => p.id === +formData.whoId);
    if (!person) return;
    if (payType === 'pay') {
      await api.recordPayment(person.name, formData.amount, formData.what, person.id);
    } else {
      await api.recordCharge(person.name, formData.amount, formData.what, person.id);
    }
    formData = { whoId: '', amount: 200, what: '' };
    await load();
  }

  async function reloadStats() {
    stats = await api.getAdminStats();
  }
</script>

<AdminShell title="Оплата">
  <div slot="actions">
    <span class="meta">Взнос 200 ₽/мес · порог 600 ₽</span>
  </div>

  {#if loading}
    <div class="skeleton" style="height:200px;border-radius:18px;"></div>
  {:else}
    <div class="stat-grid" style="margin-bottom:20px;">
      <div class="stat-card">
        <div class="label">Собрано</div>
        <div class="value">{stats.collected_month} ₽</div>
        <div class="sub">в ноябре</div>
      </div>
      <div class="stat-card">
        <div class="label">Долг</div>
        <div class="value warn">{stats.total_debt} ₽</div>
        <div class="sub">у {debts.length} человек</div>
      </div>
    </div>

    <div class="card" style="margin-bottom:20px;">
      <p class="eyebrow" style="margin:0 0 14px;">{payType === 'pay' ? 'Внести платёж' : 'Начислить трату'}</p>
      <form class="stack" style="gap:10px;" onsubmit={submit}>
        <div class="row" style="gap:6px;">
          <button type="button" class="btn btn-sm" class:btn-primary={payType === 'pay'} class:btn-secondary={payType !== 'pay'}
                  style="flex:1;" onclick={() => payType = 'pay'}>Платёж</button>
          <button type="button" class="btn btn-sm" class:btn-primary={payType === 'charge'} class:btn-secondary={payType !== 'charge'}
                  style="flex:1;" onclick={() => payType = 'charge'}>Доп. трата</button>
        </div>
        <div class="grid-2">
          <div class="form-field">
            <label for="pay-who">Кто</label>
            <select id="pay-who" required bind:value={formData.whoId}>
              <option value="" disabled>Выбери человека…</option>
              {#each allPeople as p (p.id)}
                <option value={p.id}>{p.name}{#if p.debt > 0} — долг {p.debt} ₽{/if}</option>
              {/each}
            </select>
          </div>
          <div class="form-field">
            <label for="pay-amount">Сумма, ₽</label>
            <input id="pay-amount" type="number" inputmode="numeric" min="1" step="1" required bind:value={formData.amount}>
          </div>
        </div>
        <div class="form-field">
          <label for="pay-what">{payType === 'pay' ? 'За что' : 'За что (трата)'}</label>
          <select id="pay-what" bind:value={formData.what}>
            {#if payType === 'pay'}
              <option value="" disabled>Выбери…</option>
              <option value="Наличные">Наличные</option>
              <option value="Перевод">Перевод</option>
              <option value="Карта">Карта</option>
              <option value="__custom">Другое…</option>
            {:else}
              <option value="" disabled>Выбери…</option>
              <option value="Костюм">Костюм</option>
              <option value="Реквизит">Реквизит</option>
              <option value="Транспорт">Транспорт</option>
              <option value="__custom">Другое…</option>
            {/if}
          </select>
          {#if formData.what === '__custom'}
            <input bind:value={formData.what} placeholder="Введи описание"
                   style="margin-top:6px;" aria-label="Своё описание">
          {/if}
        </div>
        <button type="submit" class="btn btn-primary btn-sm">
          {payType === 'pay' ? 'Записать платёж' : 'Начислить трату'}
        </button>
      </form>
    </div>

    <div class="card">
      <p class="eyebrow" style="margin:0 0 10px;">Должники</p>
      {#each debts as d (d.name)}
        <div class="list-row" style="grid-template-columns:1fr auto;">
          <div class="body">
            <div class="title">{d.name}</div>
            <div class="sub">{d.akadem ? 'академ' : 'активен'}</div>
          </div>
          <span class="num" style="font-weight:600;color:{d.debt > 600 ? 'var(--accent-dark)' : 'var(--fg)'};">
            {d.debt} ₽{d.debt > 600 ? ' · порог' : ''}
          </span>
        </div>
      {:else}
        <p class="meta" style="text-align:center;padding:16px;">Все оплатили</p>
      {/each}
    </div>
  {/if}
</AdminShell>
