<script>
  import AdminShell from '../../components/AdminShell.svelte';
  import { api } from '../../lib/api.js';

  let people = [];
  let loading = true;
  let search = '';

  async function load() {
    people = await api.getPeople();
    loading = false;
  }
  load();

  async function toggleAkadem(person) {
    await api.toggleAkadem(person.id, !person.akadem);
    people = [...people];
  }

  $: filtered = search
    ? people.filter(p =>
        p.name.toLowerCase().includes(search.toLowerCase()) ||
        (p.tg ?? '').toLowerCase().includes(search.toLowerCase()))
    : people;

  const statusLabels = { active: 'Активен', paused: 'Академ', banned: 'Бан', guest: 'Гость' };
</script>

<AdminShell title="Люди">
  <div slot="actions">
    <input type="search" placeholder="Поиск по имени…" bind:value={search}
           style="padding:8px 14px;border:1px solid var(--border);border-radius:10px;background:var(--surface);font:inherit;font-size:14px;min-width:200px;"
           aria-label="Поиск людей">
  </div>

  {#if loading}
    <div class="skeleton" style="height:200px;border-radius:18px;"></div>
  {:else}
    <div class="card">
      <p class="meta" style="margin:0 0 10px;">Тумблер — академ · тап по имени — чат</p>
      {#each filtered as p (p.id)}
        <div class="list-row" style="grid-template-columns:40px 1fr auto;">
          <div class="avatar">{p.name[0]}</div>
          <div class="body">
            <div class="title">{p.name}</div>
            <div class="sub">{p.vk ? 'VK' : ''} {p.tg ? '· ' + p.tg : ''}</div>
          </div>
          <div class="row" style="gap:10px;">
            <div style="display:flex;flex-direction:column;align-items:flex-end;gap:2px;">
              <span class="tag" class:status-open={p.status === 'active'}
                    class:status-warn={p.status === 'banned'}
                    style="font-size:10px;">{statusLabels[p.status]}</span>
              <span class="num" style="font-size:12px;color:{p.debt > 0 ? 'var(--accent-dark)' : 'var(--fg-faint)'};">
                {p.debt} ₽
              </span>
            </div>
            <button class="toggle" class:on={p.akadem} role="switch" aria-checked={p.akadem}
                    aria-label="Академ: {p.name}" tabindex="0"
                    onclick={() => toggleAkadem(p)}
                    onkeydown={e => (e.key === ' ' || e.key === 'Enter') && (e.preventDefault(), toggleAkadem(p))}>
            </button>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</AdminShell>
