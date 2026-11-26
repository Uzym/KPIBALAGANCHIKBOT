<script>
  import MemberShell from '../../components/MemberShell.svelte';
  import { api } from '../../lib/api.js';
  import { navigate } from '../../lib/router.js';

  let events = [];
  let loading = true;
  let eventFilter = 'Все'; // Все | Идёт запись | Закрыта | Завершено

  async function load() {
    loading = true;
    events = await api.getEvents();
    loading = false;
  }
  load();

  $: filtered = eventFilter === 'Все'
    ? events
    : events.filter(e => {
        if (eventFilter === 'Идёт запись') return e.status === 'active';
        if (eventFilter === 'Закрыта') return e.status === 'closed';
        if (eventFilter === 'Завершено') return e.status === 'finished';
        return true;
      });

  async function vote(eventId, answer) {
    const updated = await api.vote(eventId, answer);
    if (updated && updated.id) {
      const idx = events.findIndex(e => e.id === eventId);
      if (idx >= 0) events[idx] = updated;
    }
    events = [...events];
  }

  function fmtWhen(ev) {
    const d = new Date(ev.starts_at);
    const days = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];
    return `${days[d.getDay()]} ${d.getDate()} ноя, ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`;
  }
</script>

<MemberShell title="Афиша">
  <!-- фильтр -->
  <div class="pad" style="padding-bottom:0;">
    <div class="filter-row" role="tablist" aria-label="Фильтр событий">
      {#each ['Все', 'Идёт запись', 'Закрыта', 'Завершено'] as f}
        <button class="filter-chip" class:active={eventFilter === f}
                role="tab" aria-selected={eventFilter === f}
                onclick={() => eventFilter = f}>{f}</button>
      {/each}
    </div>
  </div>

  {#if loading}
    <div class="pad stack">
      <div class="skeleton" style="height:200px;border-radius:18px;"></div>
      <div class="skeleton" style="height:80px;border-radius:18px;"></div>
    </div>
  {:else}
    <div class="pad stack" style="gap:12px;">
      {#each filtered as ev (ev.id)}
        {#if ev.status === 'active'}
          <article class="card event-card">
            {#if ev.id === events[0]?.id}
              <p class="act">Ближайший акт</p>
            {/if}
            <h2 class="title clickable" onclick={() => navigate(`/member/event/${ev.id}`)}
                role="link" tabindex="0"
                onkeydown={e => e.key === 'Enter' && navigate(`/member/event/${ev.id}`)}>{ev.title}</h2>
            <div class="when">{fmtWhen(ev)}</div>
            {#if ev.place}<div class="place">{ev.place}</div>{/if}
            {#if ev.note}<p class="note">{ev.note}</p>{/if}
            <div class="rsvp-row" role="group" aria-label="Запись на {ev.title}">
              <button class="rsvp-btn" data-vote="yes" class:selected={ev.my_vote === 'yes'}
                      onclick={() => vote(ev.id, 'yes')}>
                <span class="label">Пойду</span><span class="count">{ev.counts.yes}</span>
              </button>
              <button class="rsvp-btn" data-vote="maybe" class:selected={ev.my_vote === 'maybe'}
                      onclick={() => vote(ev.id, 'maybe')}>
                <span class="label">Возможно</span><span class="count">{ev.counts.maybe}</span>
              </button>
              <button class="rsvp-btn" data-vote="no" class:selected={ev.my_vote === 'no'}
                      onclick={() => vote(ev.id, 'no')}>
                <span class="label">Не приду</span><span class="count">{ev.counts.no}</span>
              </button>
            </div>
          </article>
        {:else}
          <article class="card clickable" role="link" tabindex="0"
                   onclick={() => navigate(`/member/event/${ev.id}`)}
                   onkeydown={e => e.key === 'Enter' && navigate(`/member/event/${ev.id}`)}
                   aria-label="Открыть {ev.title}">
            <div class="row-between">
              <span class="tag" class:status-closed={ev.status === 'closed'}>
                {ev.status === 'closed' ? 'Запись закрыта' : 'Событие'}
              </span>
              <span class="meta">{new Date(ev.starts_at).getDate()} дек</span>
            </div>
            <h3 class="h3" style="margin:10px 0 4px;">{ev.title}</h3>
            <p class="meta">{ev.place}</p>
          </article>
        {/if}
      {/each}
      {#if filtered.length === 0}
        <div class="empty-state">
          <div class="icon-circle">
            <svg viewBox="0 0 24 24" style="width:28px;height:28px;stroke:currentColor;fill:none;stroke-width:1.5;"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>
          </div>
          <h3>Нет событий</h3>
          <p>В категории «{eventFilter}» пока пусто</p>
        </div>
      {/if}
    </div>
  {/if}
</MemberShell>

<style>
  .event-card { padding: 20px; }
  .act { font-family: var(--font-display); font-style: italic; font-size: 14px; color: var(--accent); margin: 0 0 4px; }
  .title {
    font-family: var(--font-display); font-size: 22px; font-weight: 700;
    letter-spacing: -0.02em; line-height: 1.15; margin: 0 0 6px; color: var(--fg);
  }
  .title.clickable { cursor: pointer; }
  .title.clickable:hover { text-decoration: underline; }
  .title.clickable:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .when, .place { color: var(--fg-mute); font-size: var(--fs-small); margin-top: 2px; }
  .note { color: var(--fg-mute); font-size: 14px; margin: 8px 0 0; }
  .clickable { cursor: pointer; transition: transform var(--dur) var(--ease); }
  .clickable:hover { transform: translateY(-2px); }
  .clickable:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
</style>
