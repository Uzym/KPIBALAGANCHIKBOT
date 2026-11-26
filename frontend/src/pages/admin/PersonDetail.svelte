<script>
  import AdminShell from '../../components/AdminShell.svelte';
  import { api } from '../../lib/api.js';
  import { path } from '../../lib/router.js';

  let person = null;
  let feeHistory = null;
  let attendance = [];
  let loading = true;
  let chatOpen = false;
  let chatInput = '';
  let chatMsgs = [];

  $: personId = $path.split('/').pop();

  async function load() {
    if (!personId) return;
    try {
      const people = await api.getPeople();
      person = people.find(p => p.id === +personId) ?? null;
      feeHistory = await api.getPersonFees(+personId);
      attendance = await api.getPersonAttendance(+personId);
    } catch (e) {
      console.warn('person load error:', e);
    } finally {
      loading = false;  // ВСЕГДА снимаем loading
    }
  }
  $: personId, load();

  async function toggleAkadem() {
    if (!person) return;
    person = await api.toggleAkadem(person.id, !person.akadem);
  }

  function sendChat() {
    const text = chatInput.trim();
    if (!text) return;
    const now = new Date().toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' });
    chatMsgs.push({ from: 'me', text, time: now });
    chatMsgs = chatMsgs;
    chatInput = '';
    api.sendMessage(text);
  }

  const answerIcons = { yes: '✓', maybe: '?', no: '✗' };
  const answerLabels = { yes: 'Пойдёт', maybe: 'Возможно', no: 'Не прийдёт' };
  const kindLabels = { accrual: 'Начисление', payment: 'Платёж', expense: 'Трата' };
  const statusLabels = { active: 'Активен', paused: 'Академ', banned: 'Бан', guest: 'Гость' };
</script>

<AdminShell title={person?.name ?? 'Профиль'}>
  {#if loading}
    <div class="skeleton" style="height:200px;border-radius:18px;"></div>
  {:else if person}
    <div class="stack" style="gap:16px;">
      <!-- информация -->
      <div class="card">
        <div class="row-between" style="margin-bottom:12px;">
          <h3 style="margin:0;font-family:var(--font-display);font-size:22px;font-weight:700;">{person.name}</h3>
          <span class="tag" class:status-open={person.status === 'active'}
                class:status-warn={person.status === 'banned'}>
            {statusLabels[person.status] ?? person.status}
          </span>
        </div>
        <div class="stack" style="gap:6px;font-size:14px;color:var(--fg-mute);">
          {#if person.vk}<span>VK ID: {person.vk}</span>{/if}
          {#if person.tg}<span>Telegram: {person.tg}</span>{/if}
          <span>Долг: <strong class="num" style="color:{person.debt > 0 ? 'var(--accent-dark)' : 'var(--olive)'}">{person.debt} ₽</strong></span>
        </div>
      </div>

      <!-- академ -->
      <div class="card">
        <div class="row-between">
          <div>
            <div style="font-weight:600;font-size:14px;">Академический отпуск</div>
            <div style="font-size:12px;color:var(--fg-mute);">Взносы не начисляются</div>
          </div>
          <button class="toggle" class:on={person.akadem} role="switch"
                  aria-checked={person.akadem} aria-label="Академ"
                  onclick={toggleAkadem}></button>
        </div>
      </div>

      <!-- посещаемость -->
      <div class="card">
        <p class="eyebrow" style="margin:0 0 12px;">Где был</p>
        {#if attendance.length === 0}
          <p class="meta" style="text-align:center;padding:12px;">Нет записей на события</p>
        {:else}
          <div class="stack" style="gap:0;">
            {#each attendance as a (a.event_id)}
              <div class="list-row" style="grid-template-columns:1fr auto auto;gap:8px;">
                <div class="body">
                  <div class="title">{a.title}</div>
                  <div class="sub">{a.starts_at}</div>
                </div>
                <span class="tag" class:status-open={a.answer === 'yes'}
                      class:status-warn={a.answer === 'no'}
                      style="font-size:10px;">
                  {answerLabels[a.answer] ?? a.answer}
                  {#if a.prev_answer}(был {answerLabels[a.prev_answer]}){/if}
                </span>
                {#if a.attended}
                  <span class="tag status-open" style="font-size:10px;">Был</span>
                {:else if a.status === 'finished'}
                  <span class="tag" style="font-size:10px;">Не отметили</span>
                {/if}
              </div>
            {/each}
          </div>
        {/if}
      </div>

      <!-- история операций -->
      <div class="card">
        <p class="eyebrow" style="margin:0 0 12px;">История операций</p>
        {#if feeHistory?.history?.length}
          <div class="stack" style="gap:0;">
            {#each feeHistory.history as h, i (i)}
              <div class="list-row" style="grid-template-columns:1fr auto;gap:8px;">
                <div class="body">
                  <div class="title">{kindLabels[h.kind] ?? h.kind}{#if h.label} · {h.label}{/if}</div>
                  <div class="sub">{h.date}{#if h.month} · {h.month}{/if}</div>
                </div>
                <span class="num" style="font-weight:600;color:{h.amount < 0 ? 'var(--olive)' : h.kind === 'payment' ? 'var(--olive)' : 'var(--fg-mute)'};">
                  {h.amount > 0 ? '+' : ''}{h.amount} ₽
                </span>
              </div>
            {/each}
          </div>
        {:else}
          <p class="meta" style="text-align:center;padding:12px;">Нет операций</p>
        {/if}
      </div>

      <!-- чат -->
      <div class="card" style="padding:0;overflow:hidden;">
        <button class="chat-toggle" onclick={() => chatOpen = !chatOpen}>
          <svg viewBox="0 0 24 24" class="ic"><path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5c-1.5 0-3-.4-4.2-1.1L3 20l1.1-5.3A8.5 8.5 0 1 1 21 11.5z"/></svg>
          <span>Написать</span>
          <svg viewBox="0 0 24 24" class="ic chev" class:open={chatOpen}><path d="M6 9l6 6 6-6"/></svg>
        </button>
        {#if chatOpen}
          <div class="chat-list">
            {#each chatMsgs as m}
              <div class="chat-msg {m.from === 'me' ? 'out' : 'in'}">
                {m.text}<span class="time">{m.time}</span>
              </div>
            {/each}
          </div>
          <div class="chat-input">
            <input type="text" placeholder="Сообщение…" bind:value={chatInput}
                   onkeydown={e => e.key === 'Enter' && sendChat()}
                   aria-label="Текст сообщения">
            <button onclick={sendChat} aria-label="Отправить">
              <svg viewBox="0 0 24 24" class="ic"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
            </button>
          </div>
        {/if}
      </div>
    </div>
  {/if}
</AdminShell>

<style>
  .chat-toggle {
    display: flex; align-items: center; gap: 10px; width: 100%;
    padding: 14px 16px; background: none; border: 0; cursor: pointer;
    font: inherit; font-size: 14px; font-weight: 500; color: var(--fg);
  }
  .chat-toggle:hover { background: rgba(21,20,15,0.03); }
  .chat-toggle .ic { width: 18px; height: 18px; stroke: currentColor; fill: none; stroke-width: 1.7; }
  .chat-toggle .chev { margin-left: auto; transition: transform var(--dur) var(--ease); }
  .chat-toggle .chev.open { transform: rotate(180deg); }
  .chat-list { display: flex; flex-direction: column; padding: 8px 16px; max-height: 300px; overflow-y: auto; }
  .chat-msg { max-width: 78%; padding: 10px 14px; border-radius: 16px; font-size: 14px; line-height: 1.4; margin-bottom: 6px; }
  .chat-msg.out { align-self: flex-end; background: var(--accent); color: #fff; border-bottom-right-radius: 4px; }
  .chat-msg.in { align-self: flex-start; background: var(--bg); color: var(--fg-soft); border: 1px solid var(--border-light); border-bottom-left-radius: 4px; }
  .chat-msg .time { font-family: var(--font-mono); font-size: 10px; opacity: 0.6; margin-top: 4px; display: block; }
  .chat-input { display: flex; gap: 8px; padding: 10px 16px; border-top: 1px solid var(--border-light); }
  .chat-input input {
    flex: 1; padding: 10px 16px; border: 1px solid var(--border); border-radius: var(--radius-pill);
    background: var(--bg); font: inherit; font-size: 14px;
  }
  .chat-input input:focus-visible { outline: 2px solid var(--accent); outline-offset: 0; }
  .chat-input button {
    width: 40px; height: 40px; border-radius: 50%; border: 0;
    background: var(--accent); color: #fff; cursor: pointer; display: grid; place-items: center;
  }
  .chat-input button .ic { width: 16px; height: 16px; stroke: currentColor; fill: none; stroke-width: 1.7; }
</style>
