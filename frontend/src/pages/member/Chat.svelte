<script>
  import { api } from '../../lib/api.js';

  let messages = [];
  let input = '';

  async function load() {
    messages = await api.getMessages();
  }
  load();

  function send() {
    const text = input.trim();
    if (!text) return;
    const now = new Date().toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' });
    messages.push({ id: Date.now(), from: 'me', text, time: now });
    messages = messages;
    input = '';
    api.sendMessage(text);
  }

  function onKey(e) {
    if (e.key === 'Enter') send();
  }
</script>

<div class="chat-shell">
  <header class="chat-header">
    <div>
      <p class="greeting">Сообщения</p>
      <h1 class="h1">Руководитель</h1>
    </div>
  </header>

  <div class="chat-list">
    {#each messages as m (m.id)}
      <div class="chat-msg {m.from === 'me' ? 'out' : 'in'}">
        {m.text}
        <span class="time">{m.time}</span>
      </div>
    {/each}
  </div>

  <div class="chat-input">
    <input type="text" placeholder="Сообщение…" bind:value={input}
           onkeydown={onKey} aria-label="Текст сообщения">
    <button onclick={send} aria-label="Отправить">
      <svg viewBox="0 0 24 24" class="ic"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"/></svg>
    </button>
  </div>
</div>

<style>
  .chat-shell {
    max-width:480px; margin:0 auto; min-height:100vh;
    display:flex; flex-direction:column;
  }
  .chat-header { padding:8px 20px 12px; }
  .greeting {
    font-family:var(--font-mono); font-size:var(--fs-micro);
    letter-spacing:0.08em; text-transform:uppercase; color:var(--fg-mute); margin:0 0 4px;
  }
  .chat-list { flex:1; overflow-y:auto; padding:8px 16px; }
  .chat-msg {
    max-width:78%; padding:10px 14px; border-radius:16px;
    font-size:14px; line-height:1.4; margin-bottom:6px;
    display:flex; flex-direction:column;
  }
  .chat-msg.out { align-self:flex-end; background:var(--accent); color:#fff; border-bottom-right-radius:4px; }
  .chat-msg.in { align-self:flex-start; background:var(--surface); color:var(--fg-soft); border:1px solid var(--border-light); border-bottom-left-radius:4px; }
  .chat-msg .time { font-family:var(--font-mono); font-size:10px; opacity:0.6; margin-top:4px; }
  .chat-input {
    display:flex; gap:8px; padding:10px 16px calc(10px + env(safe-area-inset-bottom, 0));
    border-top:1px solid var(--border-light); background:var(--surface);
  }
  .chat-input input {
    flex:1; padding:10px 16px; border:1px solid var(--border); border-radius:var(--radius-pill);
    background:var(--bg); font:inherit; font-size:14px; min-height:40px;
  }
  .chat-input input:focus-visible { outline:2px solid var(--accent); outline-offset:0; }
  .chat-input button {
    width:40px; height:40px; border-radius:50%; border:0;
    background:var(--accent); color:#fff; cursor:pointer;
    display:grid; place-items:center; flex-shrink:0;
  }
  .chat-input button:focus-visible { outline:2px solid var(--accent-dark); outline-offset:2px; }
  .ic { width:18px; height:18px; stroke:currentColor; fill:none; stroke-width:1.7; stroke-linecap:round; stroke-linejoin:round; }
</style>
