<script>
  import AdminShell from '../../components/AdminShell.svelte';
  import { api } from '../../lib/api.js';

  let announcements = [];
  let loading = true;
  let filter = 'Все';

  async function load() {
    announcements = await api.getAnnouncements();
    loading = false;
  }
  load();

  $: filtered = filter === 'Все' ? announcements : announcements.filter(a => a.content_type === filter);

  const typeLabels = { event: 'По событию', poll: 'По опросу', global: 'Клуб' };
</script>

<AdminShell title="Объявления">
  <!-- фильтр -->
  <div class="filter-row">
    {#each ['Все', 'event', 'poll', 'global'] as f}
      <button class="filter-chip" class:active={filter === f}
              onclick={() => filter = f}>
        {f === 'Все' ? 'Все' : typeLabels[f] ?? f}
      </button>
    {/each}
  </div>

  {#if loading}
    <div class="skeleton" style="height:200px;border-radius:18px;"></div>
  {:else if filtered.length === 0}
    <div class="empty-state">
      <div class="icon-circle">
        <svg viewBox="0 0 24 24" style="width:28px;height:28px;stroke:currentColor;fill:none;stroke-width:1.5;"><path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5c-1.5 0-3-.4-4.2-1.1L3 20l1.1-5.3A8.5 8.5 0 1 1 21 11.5z"/></svg>
      </div>
      <h3>Нет объявлений</h3>
      <p>Отправь объявление из карточки события</p>
    </div>
  {:else}
    {#each filtered as ann (ann.id)}
      <article class="card ann-item">
        <div class="row-between" style="margin-bottom:8px;">
          <span class="tag" class:status-open={ann.content_type === 'event'}
                class:status-closed={ann.content_type === 'poll'}>
            {typeLabels[ann.content_type] ?? ann.content_type}
          </span>
          <span class="meta">{ann.date}</span>
        </div>
        {#if ann.target && ann.target !== ann.content_type}
          <p class="target" style="margin:0 0 6px;font-size:13px;color:var(--fg-mute);">{ann.target}</p>
        {/if}
        <p style="margin:0;font-size:14px;color:var(--fg-soft);line-height:1.5;">{ann.text}</p>
      </article>
    {/each}
  {/if}
</AdminShell>

<style>
  .ann-item {
    margin-bottom: 12px;
    transition: transform var(--dur) var(--ease);
  }
  .ann-item:hover { transform: translateY(-1px); }
  .target { font-weight: 500; }
</style>
