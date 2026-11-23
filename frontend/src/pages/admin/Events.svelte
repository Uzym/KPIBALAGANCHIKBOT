<script>
  import AdminShell from '../../components/AdminShell.svelte';
  import { api } from '../../lib/api.js';

  let events = [];
  let loading = true;
  let showCreate = false;
  let newEvent = { title: '', start: '', place: '', note: '' };

  async function load() {
    events = await api.getEvents();
    loading = false;
  }
  load();

  async function create(e) {
    e.preventDefault();
    if (!newEvent.title.trim()) return;
    await api.createEvent({ title: newEvent.title, starts_at: newEvent.start, place: newEvent.place, note: newEvent.note });
    showCreate = false;
    newEvent = { title: '', start: '', place: '', note: '' };
    await load();
  }

  function fmt(ev) {
    const d = new Date(ev.starts_at);
    return d.toLocaleDateString('ru', { weekday: 'short', day: 'numeric', month: 'short' }) +
      ', ' + d.toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' });
  }

  const statusLabels = { active: 'Идёт запись', closed: 'Закрыта', finished: 'Завершено', cancelled: 'Отменено' };
</script>

<AdminShell title="События">
  <div slot="actions">
    <button class="btn btn-primary btn-sm" onclick={() => showCreate = !showCreate}>
      {showCreate ? 'Скрыть' : 'Создать'}
    </button>
  </div>

  {#if showCreate}
    <div class="card" style="margin-bottom:20px;">
      <p class="eyebrow" style="margin:0 0 14px;">Новое событие</p>
      <form class="stack" style="gap:10px;" onsubmit={create}>
        <div class="form-field">
          <label for="ev-title">Название</label>
          <input id="ev-title" required bind:value={newEvent.title} placeholder="Тренировка">
        </div>
        <div class="grid-2">
          <div class="form-field">
            <label for="ev-start">Начало</label>
            <input id="ev-start" required bind:value={newEvent.start} placeholder="вт 19:00">
          </div>
          <div class="form-field">
            <label for="ev-place">Место</label>
            <input id="ev-place" bind:value={newEvent.place} placeholder="Зал №2">
          </div>
        </div>
        <div class="form-field">
          <label for="ev-note">Описание</label>
          <textarea id="ev-note" rows="2" bind:value={newEvent.note} placeholder="Что взять"></textarea>
        </div>
        <button type="submit" class="btn btn-primary btn-sm">Опубликовать</button>
      </form>
    </div>
  {/if}

  {#if loading}
    <div class="skeleton" style="height:200px;border-radius:18px;"></div>
  {:else}
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>№</th><th>Название</th><th>Когда</th><th>Да</th><th>Статус</th></tr>
        </thead>
        <tbody>
          {#each events as ev (ev.id)}
            <tr>
              <td class="num" style="color:var(--fg-faint);">{ev.id}</td>
              <td style="font-weight:500;">{ev.title}</td>
              <td style="color:var(--fg-mute);">{fmt(ev)}</td>
              <td class="num">{ev.counts.yes}</td>
              <td>
                <span class="tag" class:status-open={ev.status === 'active'}
                      class:status-closed={ev.status === 'closed'}>
                  {statusLabels[ev.status] ?? ev.status}
                </span>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</AdminShell>
