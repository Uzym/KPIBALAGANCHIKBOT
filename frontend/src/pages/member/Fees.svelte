<script>
  import MemberShell from '../../components/MemberShell.svelte';
  import { api } from '../../lib/api.js';

  let fees = null;
  let loading = true;
  let reportAmount = 200;
  let reportMethod = 'Перевод';
  let reportStatus = '';

  async function load() {
    fees = await api.getFees();
    loading = false;
  }
  load();

  async function reportPayment(e) {
    e.preventDefault();
    if (!reportAmount) return;
    await api.reportPayment(reportAmount, 'перевод');
    reportStatus = `Отправлено: ${reportAmount} ₽ (${reportMethod}). Ждите подтверждения.`;
  }
</script>

<MemberShell title="Оплата" subtitle="Клубный взнос · {fees?.monthly ?? 200} ₽/мес">
  {#if loading}
    <div class="pad"><div class="skeleton" style="height:200px;border-radius:18px;"></div></div>
  {:else}
    <div class="pad stack" style="gap:12px;">
      <!-- долг -->
      <article class="card" style="text-align:center;padding:24px 20px;">
        <p class="meta" style="margin:0 0 6px;">ТВОЙ ДОЛГ</p>
        <div class="num debt">{fees.my_debt} <span class="cur">₽</span></div>
        <div class="progress" style="margin:16px auto;max-width:240px;">
          <span class:warn={fees.my_debt / fees.threshold < 1}
                class:over={fees.my_debt >= fees.threshold}
                style="width:{Math.min(100, fees.my_debt / fees.threshold * 100)}%;"></span>
        </div>
        <p class="meta" style="margin:0;">Порог — {fees.threshold} ₽</p>
      </article>

      <!-- я оплатил -->
      <article class="card">
        <p class="eyebrow" style="margin:0 0 10px;">Я оплатил</p>
        <form class="stack" style="gap:10px;" onsubmit={reportPayment}>
          <div class="form-field">
            <label for="fr-amount">Сумма, ₽</label>
            <input id="fr-amount" type="number" inputmode="numeric" min="1" step="1"
                   required bind:value={reportAmount}>
          </div>
          <button type="submit" class="btn btn-primary btn-sm">Отправить руководителю</button>
        </form>
        {#if reportStatus}
          <p class="meta" style="margin:10px 0 0;color:var(--olive);">{reportStatus}</p>
        {/if}
      </article>

      <!-- история -->
      <article class="card">
        <p class="eyebrow" style="margin:0 0 10px;">История</p>
        {#each fees.history as h (h.id)}
          <div class="list-row" style="grid-template-columns:1fr auto;">
            <div class="body">
              <div class="title">{h.label}</div>
              <div class="sub">{h.date}</div>
            </div>
            <span class="num" style="color:{h.amount < 0 ? 'var(--olive)' : 'var(--fg-mute)'};">
              {h.amount > 0 ? '+' : ''}{h.amount} ₽
            </span>
          </div>
        {/each}
      </article>
    </div>
  {/if}
</MemberShell>

<style>
  .debt { font-size:48px; font-weight:600; letter-spacing:-0.03em; line-height:1; color:var(--fg); }
  .cur { font-size:22px; }
</style>
