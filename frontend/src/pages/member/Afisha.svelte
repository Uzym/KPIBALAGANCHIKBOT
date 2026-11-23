<script>
  import MemberShell from '../../components/MemberShell.svelte';
  import { api } from '../../lib/api.js';
  import { navigate } from '../../lib/router.js';

  let events = [];
  let view = 'list'; // 'list' | 'cal'
  let loading = true;

  async function load() {
    loading = true;
    events = await api.getEvents();
    loading = false;
  }
  load();

  async function vote(eventId, answer) {
    await api.vote(eventId, answer);
    events = [...events];
  }

  // календарь
  const eventsByDay = { 25: 'Тренировка 19:00', 28: 'Репетиция 18:00' };
  const today = 23;
  let calDetail = null;

  function calDay(day, label) {
    calDetail = { day, label };
  }

  function fmtWhen(ev) {
    const d = new Date(ev.starts_at);
    const days = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];
    return `${days[d.getDay()]} ${d.getDate()} ноя, ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`;
  }
</script>

<MemberShell title="Афиша" subtitle="Воскресенье · 23 ноября">
  <div slot="actions">
    <div class="cal-switch" role="tablist" aria-label="Вид">
      <button class:active={view === 'list'} onclick={() => view = 'list'}>Список</button>
      <button class:active={view === 'cal'} onclick={() => view = 'cal'}>Календарь</button>
    </div>
  </div>

  {#if loading}
    <div class="pad stack">
      <div class="skeleton" style="height:200px;border-radius:18px;"></div>
      <div class="skeleton" style="height:80px;border-radius:18px;"></div>
    </div>
  {:else if view === 'cal'}
    <!-- календарь -->
    <div class="pad stack" style="gap:10px;">
      <div class="cal-month-nav">
        <button aria-label="Предыдущий"><svg class="ic-sm" viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6"/></svg></button>
        <span class="h3" style="font-family:var(--font-display);">Ноябрь 2026</span>
        <button aria-label="Следующий"><svg class="ic-sm" viewBox="0 0 24 24"><path d="M9 18l6-6-6-6"/></svg></button>
      </div>
      <div class="card" style="padding:12px;">
        <div class="cal-grid">
          {#each ['Вс','Пн','Вт','Ср','Чт','Пт','Сб'] as d}<div class="cal-dow">{d}</div>{/each}
          {#each Array(30) as _, i}
            {@const day = i + 1}
            {@const has = eventsByDay[day]}
            <div class="cal-day"
                 class:today={day === today}
                 class:has-event={has}
                 role={has ? 'button' : undefined}
                 tabindex={has ? 0 : undefined}
                 aria-label={has ? `${day} ноября: ${has}` : undefined}
                 onclick={() => has && calDay(day, has)}
                 onkeydown={() => has && event.key === 'Enter' && calDay(day, has)}
            >{day}</div>
          {/each}
        </div>
      </div>
      {#if calDetail}
        <div class="card">
          <p class="eyebrow" style="margin:0 0 8px;">{calDetail.day} ноября</p>
          <div class="row-between">
            <span class="h3">{calDetail.label}</span>
            <span class="pill count">7</span>
          </div>
        </div>
      {/if}
    </div>
  {:else}
    <!-- список -->
    <div class="pad stack" style="gap:12px;">
      {#each events as ev (ev.id)}
        {#if ev.status === 'active'}
          <article class="card event-card">
            {#if ev.id === events[0]?.id}
              <p class="act">Ближайший акт</p>
            {/if}
            <h2 class="title">{ev.title}</h2>
            <div class="when">{fmtWhen(ev)}</div>
            {#if ev.place}<div class="place">{ev.place}</div>{/if}
            {#if ev.note}<p class="note">{ev.note}</p>{/if}
            <div class="rsvp-row" role="group" aria-label="Запись на {ev.title}">
              <button class="rsvp-btn" class:selected={ev.my_vote === 'yes'}
                      onclick={() => vote(ev.id, 'yes')}>
                <span class="label">Пойду</span><span class="count">{ev.counts.yes}</span>
              </button>
              <button class="rsvp-btn" class:selected={ev.my_vote === 'maybe'}
                      onclick={() => vote(ev.id, 'maybe')}>
                <span class="label">Возможно</span><span class="count">{ev.counts.maybe}</span>
              </button>
              <button class="rsvp-btn" class:selected={ev.my_vote === 'no'}
                      onclick={() => vote(ev.id, 'no')}>
                <span class="label">Не приду</span><span class="count">{ev.counts.no}</span>
              </button>
            </div>
          </article>
        {:else}
          <article class="card clickable" role="link" tabindex="0" onclick={() => navigate('/member')}>
            <div class="row-between">
              <span class="tag" class:status-closed={ev.status === 'closed'}>{ev.status === 'closed' ? 'Запись закрыта' : 'Событие'}</span>
              <span class="meta">{new Date(ev.starts_at).getDate()} дек</span>
            </div>
            <h3 class="h3" style="margin:10px 0 4px;">{ev.title}</h3>
            <p class="meta">{ev.place}</p>
          </article>
        {/if}
      {/each}
    </div>
  {/if}
</MemberShell>

<style>
  .cal-switch { display:flex; gap:0; border:1px solid var(--border); border-radius:var(--radius-pill); overflow:hidden; }
  .cal-switch button { padding:6px 14px; border:0; background:transparent; font:inherit; font-size:12px; font-weight:500; color:var(--fg-mute); cursor:pointer; }
  .cal-switch button.active { background:var(--fg); color:var(--surface); }
  .cal-switch button:focus-visible { outline:2px solid var(--accent); outline-offset:-2px; }

  .cal-month-nav { display:flex; align-items:center; justify-content:space-between; padding:0 4px; }
  .cal-month-nav button { width:32px; height:32px; border:1px solid var(--border); border-radius:50%; background:var(--surface); color:var(--fg); cursor:pointer; display:grid; place-items:center; }
  .cal-month-nav button:focus-visible { outline:2px solid var(--accent); }
  .ic-sm { width:16px; height:16px; stroke:currentColor; fill:none; stroke-width:1.7; }

  .event-card { padding:20px; }
  .act { font-family:var(--font-display); font-style:italic; font-size:14px; color:var(--accent); margin:0 0 4px; }
  .title { font-family:var(--font-display); font-size:22px; font-weight:700; letter-spacing:-0.02em; line-height:1.15; margin:0 0 6px; color:var(--fg); }
  .when, .place { color:var(--fg-mute); font-size:var(--fs-small); margin-top:2px; }
  .note { color:var(--fg-mute); font-size:14px; margin:8px 0 0; }
  .clickable { cursor:pointer; transition:transform var(--dur) var(--ease); }
  .clickable:hover { transform:translateY(-2px); }
  .clickable:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
</style>
