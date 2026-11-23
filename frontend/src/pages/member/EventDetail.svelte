<script>
  import MemberShell from '../../components/MemberShell.svelte';
  import { api } from '../../lib/api.js';
  import { path } from '../../lib/router.js';

  let event = null;
  let loading = true;

  // ID из пути: /member/event/12 → "12"
  $: eventId = $path.split('/').pop();

  async function load() {
    if (!eventId) return;
    event = await api.getEvent(eventId);
    loading = false;
  }
  $: eventId, load();

  async function vote(answer) {
    event = await api.vote(+eventId, answer);
  }

  function fmtWhen(ev) {
    if (!ev?.starts_at) return '';
    const d = new Date(ev.starts_at);
    return d.toLocaleDateString('ru', { weekday: 'short', day: 'numeric', month: 'short' })
      + ', ' + d.toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' });
  }

  // группировка голосов
  $: groups = event ? {
    yes: event.votes?.filter(v => v.answer === 'yes') ?? [],
    maybe: event.votes?.filter(v => v.answer === 'maybe') ?? [],
    no: event.votes?.filter(v => v.answer === 'no') ?? [],
  } : {};
</script>

<MemberShell title={event?.title ?? 'Событие'}>
  {#if loading}
    <div class="pad"><div class="skeleton" style="height:300px;border-radius:18px;"></div></div>
  {:else if event}
    <div class="pad stack" style="gap:12px;">
      <!-- карточка события -->
      <article class="card event-card">
        <h2 class="title">{event.title}</h2>
        <div class="when">{fmtWhen(event)}</div>
        {#if event.place}<div class="place">{event.place}</div>{/if}
        {#if event.note}<p class="note">{event.note}</p>{/if}
        {#if event.status === 'active'}
          <div class="rsvp-row" role="group" aria-label="Запись на {event.title}">
            <button class="rsvp-btn" data-vote="yes" class:selected={event.my_vote === 'yes'}
                    onclick={() => vote('yes')}>
              <span class="label">Пойду</span><span class="count">{event.counts.yes}</span>
            </button>
            <button class="rsvp-btn" data-vote="maybe" class:selected={event.my_vote === 'maybe'}
                    onclick={() => vote('maybe')}>
              <span class="label">Возможно</span><span class="count">{event.counts.maybe}</span>
            </button>
            <button class="rsvp-btn" data-vote="no" class:selected={event.my_vote === 'no'}
                    onclick={() => vote('no')}>
              <span class="label">Не приду</span><span class="count">{event.counts.no}</span>
            </button>
          </div>
        {:else}
          <p class="meta" style="margin-top:14px;text-align:center;">
            {event.status === 'closed' ? 'Запись закрыта' : event.status === 'finished' ? 'Завершено' : 'Отменено'}
          </p>
        {/if}
      </article>

      <!-- списки -->
      {#if event.votes?.length}
        <article class="card">
          {#each Object.entries({ 'Пойдут': groups.yes, 'Возможно': groups.maybe, 'Не придут': groups.no }) as [label, votes]}
            <div class="vote-group">
              <div class="group-label">{label} · {votes.filter(v => !v.prev).length}</div>
              <div class="names">
                {#each votes as v}
                  {#if v.prev}
                    <span class="struck">{v.name}</span>
                    <span class="struck-note">({v.prevTime})</span>
                  {:else}
                    <span>{v.name}{#if v.tag}&nbsp;<small class="name-tag">{v.tag}</small>{/if}</span>
                  {/if}
                {/each}
                {#if !votes.length}<span style="color:var(--fg-faint)">—</span>{/if}
              </div>
            </div>
          {/each}
        </article>
      {/if}
    </div>
  {/if}
</MemberShell>

<style>
  .event-card { padding: 20px; }
  .title { font-family: var(--font-display); font-size: 22px; font-weight: 700; letter-spacing: -0.02em; line-height: 1.15; margin: 0 0 6px; color: var(--fg); }
  .when, .place { color: var(--fg-mute); font-size: var(--fs-small); margin-top: 2px; }
  .note { color: var(--fg-mute); font-size: 14px; margin: 8px 0 0; }
  .vote-group { padding: 12px 0; border-bottom: 1px solid var(--border-light); }
  .vote-group:last-child { border-bottom: 0; }
  .group-label { font-family: var(--font-mono); font-size: var(--fs-micro); letter-spacing: 0.06em; text-transform: uppercase; color: var(--fg-mute); margin-bottom: 6px; }
  .names { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: var(--fs-small); color: var(--fg-soft); }
  .struck { text-decoration: line-through; text-decoration-thickness: 1.5px; color: var(--fg-faint); }
  .struck-note { font-family: var(--font-mono); font-size: var(--fs-micro); color: var(--fg-faint); font-style: italic; }
  .name-tag { color: var(--fg-faint); font-family: var(--font-mono); font-size: 10px; }
</style>
