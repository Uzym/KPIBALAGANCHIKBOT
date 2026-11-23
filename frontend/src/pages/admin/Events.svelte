<script>
  import AdminShell from '../../components/AdminShell.svelte';
  import { api } from '../../lib/api.js';

  let events = [];
  let loading = true;
  let showCreate = false;
  let eventFilter = 'Все';
  let editingEvent = null;
  let expandedEvent = null; // id раскрытой карточки
  let announceText = '';

  let newEvent = { title: '', date: '', time: '', place: '', note: '' };

  async function load() {
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

  function toggleCreate() {
    showCreate = !showCreate;
    if (showCreate) {
      editingEvent = null;
      newEvent = { title: '', date: '', time: '', place: '', note: '' };
    }
  }

  function startEdit(ev) {
    editingEvent = ev;
    showCreate = true;
    const d = new Date(ev.starts_at);
    newEvent = {
      title: ev.title,
      date: d.toISOString().slice(0, 10),
      time: d.toTimeString().slice(0, 5),
      place: ev.place || '',
      note: ev.note || '',
    };
  }

  async function submit(e) {
    e.preventDefault();
    if (!newEvent.title.trim() || !newEvent.date || !newEvent.time) return;
    const starts_at = `${newEvent.date}T${newEvent.time}`;
    if (editingEvent) {
      await api.updateEvent(editingEvent.id, {
        title: newEvent.title, starts_at, place: newEvent.place, note: newEvent.note,
      });
      await load();
    } else {
      await api.createEvent({ title: newEvent.title, starts_at, place: newEvent.place, note: newEvent.note });
      await load();
    }
    toggleCreate();
  }

  async function closeEvent(id) {
    await api.closeEvent(id);
    await load();
  }

  async function reopenEvent(id) {
    await api.reopenEvent(id);
    await load();
  }

  async function cancelEvent(id) {
    await api.cancelEvent(id);
    await load();
  }

  async function deleteEvent(id) {
    await api.deleteEvent(id);
    await load();
  }

  function toggleExpand(id) {
    expandedEvent = expandedEvent === id ? null : id;
    announceText = '';
  }

  async function sendAnnouncement(e, ev) {
    e.preventDefault();
    if (!announceText.trim()) return;
    const result = await api.announceEvent(ev.id, announceText);
    if (!ev.announcements) ev.announcements = [];
    ev.announcements.unshift({ text: announceText, time: 'сейчас' });
    events = [...events];
    announceText = '';
  }

  // посещаемость (mock)
  let attendance = new Map(); // event_id → { name, present }[]
  function initAttendance(ev) {
    if (!attendance.has(ev.id)) {
      attendance.set(ev.id, (ev.votes || []).map(v => ({ name: v.name, present: false })));
    }
    return attendance.get(ev.id);
  }

  function togglePresent(evId, name) {
    const list = attendance.get(evId);
    const p = list.find(x => x.name === name);
    if (p) p.present = !p.present;
    attendance.set(evId, [...list]);
    attendance = attendance;
  }

  function fmt(ev) {
    const d = new Date(ev.starts_at);
    return d.toLocaleDateString('ru', { weekday: 'short', day: 'numeric', month: 'short' }) +
      ', ' + d.toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' });
  }

  const statusLabels = { active: 'Идёт запись', closed: 'Запись закрыта', finished: 'Завершено', cancelled: 'Отменено' };
</script>

<AdminShell title="События">
  <div slot="actions">
    <button class="btn btn-primary btn-sm" onclick={toggleCreate}>
      {showCreate ? 'Скрыть' : 'Создать'}
    </button>
  </div>

  <!-- фильтр -->
  <div class="filter-row">
    {#each ['Все', 'Идёт запись', 'Закрыта', 'Завершено'] as f}
      <button class="filter-chip" class:active={eventFilter === f}
              onclick={() => eventFilter = f}>{f}</button>
    {/each}
  </div>

  <!-- форма создания/редактирования -->
  {#if showCreate}
    <div class="card" style="margin-bottom:20px;">
      <p class="eyebrow" style="margin:0 0 14px;">
        {editingEvent ? 'Редактировать событие' : 'Новое событие'}
      </p>
      <form class="stack" style="gap:10px;" onsubmit={submit}>
        <div class="form-field">
          <label for="ev-title">Название</label>
          <input id="ev-title" required bind:value={newEvent.title}
                 placeholder="Тренировка" list="known-titles">
          <datalist id="known-titles">
            <option value="Тренировка по импровизации"><option value="Репетиция показа">
            <option value="Осенний показ"><option value="Вступительная встреча">
          </datalist>
        </div>
        <div class="grid-2">
          <div class="form-field">
            <label for="ev-date">Дата</label>
            <input id="ev-date" type="date" required bind:value={newEvent.date}>
          </div>
          <div class="form-field">
            <label for="ev-time">Время</label>
            <input id="ev-time" type="time" required step="300" bind:value={newEvent.time}>
          </div>
        </div>
        <div class="form-field">
          <label for="ev-place">Место</label>
          <input id="ev-place" bind:value={newEvent.place} placeholder="Зал №2" list="known-places">
          <datalist id="known-places">
            <option value="Зал №2, корпус 4"><option value="Актовый зал">
            <option value="Корпус 9, аудитория 312">
          </datalist>
        </div>
        <div class="form-field">
          <label for="ev-note">Описание</label>
          <textarea id="ev-note" rows="2" bind:value={newEvent.note} placeholder="Что взять"></textarea>
        </div>
        <div class="row" style="gap:10px;">
          <button type="submit" class="btn btn-primary btn-sm" style="flex:1;">
            {editingEvent ? 'Сохранить' : 'Опубликовать'}
          </button>
          <button type="button" class="btn btn-secondary btn-sm" style="flex:1;"
                  onclick={toggleCreate}>Отмена</button>
        </div>
      </form>
    </div>
  {/if}

  <!-- список карточек -->
  {#if loading}
    <div class="skeleton" style="height:200px;border-radius:18px;"></div>
  {:else}
    {#each filtered as ev (ev.id)}
      <div class="card event-item">
        <!-- шапка: клик = раскрыть/свернуть -->
        <button class="event-header" onclick={() => toggleExpand(ev.id)}
                aria-expanded={expandedEvent === ev.id}
                aria-label="{expandedEvent === ev.id ? 'Свернуть' : 'Раскрыть'} {ev.title}">
          <div class="event-info">
            <h3 class="h3">{ev.title}</h3>
            <p class="meta">{fmt(ev)}{#if ev.place} · {ev.place}{/if}</p>
          </div>
          <div class="event-badges">
            <span class="tag" class:status-open={ev.status === 'active'}
                  class:status-closed={ev.status === 'closed'}>
              {statusLabels[ev.status] ?? ev.status}
            </span>
            <svg class="chev" class:open={expandedEvent === ev.id} viewBox="0 0 24 24">
              <path d="M6 9l6 6 6-6"/>
            </svg>
          </div>
        </button>

        <!-- счётчики -->
        <div class="row" style="gap:12px;margin-bottom:10px;">
          <span class="pill count">Пойду: {ev.counts.yes}</span>
          <span class="pill count">Возможно: {ev.counts.maybe}</span>
          <span class="pill count">Нет: {ev.counts.no}</span>
        </div>

        <!-- раскрытая панель -->
        {#if expandedEvent === ev.id}
          <div class="event-details">
            <!-- кто идёт -->
            {#if ev.votes?.length}
              <div class="detail-section">
                <p class="eyebrow" style="margin:0 0 8px;">Кто пойдёт</p>
                <div class="names">
                  {#each ev.votes.filter(v => v.answer === 'yes') as v}
                    <span class="voter">{v.name}{#if v.tag}&nbsp;<small class="tag-sm">{v.tag}</small>{/if}</span>
                  {/each}
                </div>
              </div>
            {/if}

            <!-- объявления -->
            <div class="detail-section">
              <p class="eyebrow" style="margin:0 0 8px;">Объявления</p>
              {#if ev.announcements?.length}
                {#each ev.announcements as ann}
                  <div class="announcement-item">
                    <span class="meta">{ann.time}</span>
                    <p style="margin:4px 0 0;font-size:14px;">{ann.text}</p>
                  </div>
                {/each}
              {:else}
                <p class="meta" style="margin:0;">Пока нет</p>
              {/if}
              <form class="row" style="gap:8px;margin-top:10px;" onsubmit={e => sendAnnouncement(e, ev)}>
                <input class="announce-input" placeholder="Текст объявления…" bind:value={announceText}>
                <button type="submit" class="btn btn-primary btn-sm" style="flex-shrink:0;">Отправить</button>
              </form>
            </div>

            <!-- посещаемость -->
            {#if ev.status !== 'active' && ev.votes?.length}
              <div class="detail-section">
                <p class="eyebrow" style="margin:0 0 8px;">Кто пришёл</p>
                <div class="stack" style="gap:0;">
                  {#each initAttendance(ev) as p}
                    <div class="row-between" style="padding:6px 0;">
                      <span style="font-size:14px;">{p.name}</span>
                      <button class="check" class:on={p.present} role="checkbox"
                              aria-checked={p.present} aria-label="Пришёл: {p.name}"
                              onclick={() => togglePresent(ev.id, p.name)}></button>
                    </div>
                  {/each}
                </div>
              </div>
            {/if}
          </div>
        {/if}

        <!-- кнопки действий -->
        <div class="row" style="gap:8px;flex-wrap:wrap;">
          <button class="btn btn-secondary btn-sm" onclick={() => startEdit(ev)}>Изменить</button>
          {#if ev.status === 'active'}
            <button class="btn btn-secondary btn-sm" onclick={() => closeEvent(ev.id)}>Закрыть запись</button>
          {:else if ev.status === 'closed'}
            <button class="btn btn-secondary btn-sm" onclick={() => reopenEvent(ev.id)}>Открыть запись</button>
          {/if}
          {#if ev.status !== 'cancelled' && ev.status !== 'finished'}
            <button class="btn btn-secondary btn-sm" onclick={() => cancelEvent(ev.id)}>Отменить</button>
          {/if}
          <button class="btn btn-ghost btn-sm" style="color:var(--accent-dark);"
                  onclick={() => deleteEvent(ev.id)}>Удалить</button>
        </div>
      </div>
    {:else}
      <div class="empty-state">
        <div class="icon-circle">
          <svg viewBox="0 0 24 24" style="width:28px;height:28px;stroke:currentColor;fill:none;stroke-width:1.5;"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>
        </div>
        <h3>Нет событий</h3>
        <p>Создай первое событие кнопкой «Создать»</p>
      </div>
    {/each}
  {/if}
</AdminShell>

<style>
  .event-item {
    margin-bottom: 14px;
    transition: transform var(--dur) var(--ease);
  }
  .event-header {
    display: flex; align-items: flex-start; justify-content: space-between;
    gap: 12px; width: 100%; margin-bottom: 8px;
    background: none; border: 0; cursor: pointer;
    font: inherit; text-align: left; padding: 0;
  }
  .event-header:focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; border-radius: 4px; }
  .event-info h3 { margin: 0; }
  .event-info .meta { margin: 4px 0 0; }
  .event-badges { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
  .chev {
    width: 18px; height: 18px; stroke: var(--fg-faint);
    fill: none; stroke-width: 1.7; stroke-linecap: round;
    transition: transform var(--dur) var(--ease);
  }
  .chev.open { transform: rotate(180deg); }

  .event-details {
    border-top: 1px solid var(--border-light);
    padding-top: 12px; margin-bottom: 12px;
  }
  .detail-section { margin-bottom: 14px; }
  .detail-section:last-child { margin-bottom: 0; }

  .names { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: var(--fs-small); color: var(--fg-soft); }
  .voter { padding: 2px 0; }
  .tag-sm { color: var(--fg-faint); font-family: var(--font-mono); font-size: 10px; }

  .announcement-item {
    padding: 8px 12px; background: var(--surface-warm);
    border-radius: var(--radius); margin-bottom: 6px;
  }
  .announce-input {
    flex: 1; padding: 8px 14px; border: 1px solid var(--border); border-radius: 10px;
    background: var(--surface); color: var(--fg); font: inherit; font-size: 14px;
    min-height: 40px;
  }
  .announce-input:focus-visible { outline: 2px solid var(--accent); outline-offset: 0; }

  .check {
    width: 24px; height: 24px; border: 1.5px solid var(--border); border-radius: 6px;
    display: grid; place-items: center; cursor: pointer;
    transition: all var(--dur) var(--ease); flex-shrink: 0; padding: 0;
    background: var(--surface);
  }
  .check:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .check.on { background: var(--olive); border-color: var(--olive); }
  .check.on::after {
    content: ''; width: 8px; height: 5px;
    border-left: 2px solid #fff; border-bottom: 2px solid #fff;
    transform: rotate(-45deg); margin-top: -2px;
  }
</style>
