<script>
  import MemberShell from '../../components/MemberShell.svelte';
  import { api } from '../../lib/api.js';

  let polls = [];
  let loading = true;

  async function load() {
    polls = await api.getPolls();
    loading = false;
  }
  load();

  async function vote(pollId, optionId) {
    await api.pollVote(pollId, optionId);
    polls = [...polls];
  }
</script>

<MemberShell title="Опросы" subtitle="Мнение зала">
  {#if loading}
    <div class="pad"><div class="skeleton" style="height:200px;border-radius:18px;"></div></div>
  {:else}
    <div class="pad stack" style="gap:12px;">
      {#each polls as poll (poll.id)}
        <article class="card">
          <div class="row-between" style="margin-bottom:10px;">
            <span class="tag" class:status-open={poll.status === 'open'} class:status-closed={poll.status === 'closed'}>
              {poll.status === 'open' ? 'Открыт' : 'Закрыт'}
            </span>
            <span class="meta">до {poll.deadline}</span>
          </div>
          <h3 class="h3">{poll.question}</h3>
          <p class="meta" style="margin:4px 0 12px;">
            {poll.multi ? 'Мультивыбор' : 'Один вариант'} · проголосовало {poll.voted}
          </p>
          {#each poll.options as opt (opt.id)}
            <button class="poll-option"
                    class:selected={poll.my_picks.includes(opt.id)}
                    disabled={poll.status !== 'open'}
                    onclick={() => vote(poll.id, opt.id)}
                    aria-pressed={poll.my_picks.includes(opt.id)}>
              <div class="fill" style="width:{poll.voted ? Math.round(opt.count / poll.voted * 100) : 0}%;"></div>
              <span class="opt-label">{opt.label}</span>
              <span class="opt-count">{opt.count}</span>
            </button>
          {/each}
        </article>
      {/each}
    </div>
  {/if}
</MemberShell>

<style>
  .poll-option {
    display:flex; align-items:center; gap:12px; width:100%;
    padding:12px 14px; border:1px solid var(--border-light);
    border-radius:var(--radius); margin-bottom:8px; cursor:pointer;
    background:var(--surface); position:relative; overflow:hidden;
    font:inherit; text-align:left; transition:border-color var(--dur) var(--ease);
  }
  .poll-option:disabled { cursor:default; opacity:0.7; }
  .poll-option:not(:disabled):hover { border-color:var(--fg-mute); }
  .poll-option:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
  .fill { position:absolute; inset:0; background:rgba(237,111,92,0.08); transition:width 300ms var(--ease); }
  .poll-option > * { position:relative; }
  .opt-label { flex:1; font-size:14px; font-weight:500; color:var(--fg); }
  .opt-count { font-family:var(--font-mono); font-size:14px; font-weight:600; color:var(--fg-mute); }
  .poll-option.selected { border-color:var(--accent); }
  .poll-option.selected .opt-count { color:var(--accent-dark); }
</style>
