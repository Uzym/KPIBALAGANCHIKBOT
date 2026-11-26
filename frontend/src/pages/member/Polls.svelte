<script>
  import MemberShell from '../../components/MemberShell.svelte';
  import { api } from '../../lib/api.js';

  let polls = [];
  let loading = true;
  let expanded = new Set();
  let pollFilter = 'Все';

  $: filteredPolls = pollFilter === 'Все' ? polls : polls.filter(p => p.status === pollFilter); // раскрытые опции

  async function load() {
    polls = await api.getPolls();
    loading = false;
  }
  load();

  async function vote(pollId, optionId) {
    await api.pollVote(pollId, optionId);
    await load(); // перезагрузить с API — актуальные счётчики
  }

  function toggleExpand(key) {
    const next = new Set(expanded);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    expanded = next;
  }

  // mock: кто за что проголосовал (в реале — из API)
  const demoVoters = {
    'Баня': ['Аня К.', 'Боба', 'Вика', 'Гоша', 'Ева'],
    'Каток': ['Дима', 'Женя', 'Зоя'],
    'Квартирник': ['Аня К.', 'Гоша', 'Марк', 'Лиза'],
    'Кабаре': ['Аня К.', 'Боба', 'Вика', 'Гоша', 'Дима', 'Ева', 'Женя', 'Зоя', 'Марк', 'Лиза', 'Костя', 'Нина'],
    'Драма': ['Олег', 'Полина', 'Рита', 'Соня'],
  };
</script>

<MemberShell title="Опросы">
  <div class="pad" style="padding-bottom:0;">
    <div class="filter-row">
      {#each ['Все', 'open', 'closed'] as f}
        <button class="filter-chip" class:active={pollFilter === f}
                onclick={() => pollFilter = f}>
          {f === 'Все' ? 'Все' : f === 'open' ? 'Открытые' : 'Закрытые'}
        </button>
      {/each}
    </div>
  </div>
  {#if loading}
    <div class="pad"><div class="skeleton" style="height:200px;border-radius:18px;"></div></div>
  {:else}
    <div class="pad stack" style="gap:12px;">
      {#each filteredPolls as poll (poll.id)}
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
            {@const key = `${poll.id}:${opt.id}`}
            <button class="poll-option"
                    class:selected={poll.my_picks.includes(opt.id)}
                    disabled={poll.status !== 'open'}
                    onclick={() => vote(poll.id, opt.id)}
                    aria-pressed={poll.my_picks.includes(opt.id)}>
              <div class="fill" style="width:{poll.voted ? Math.round(opt.count / poll.voted * 100) : 0}%;"></div>
              <span class="opt-label">{opt.label}</span>
              <span class="opt-count">{opt.count}</span>
            </button>
            {#if poll.status !== 'open' || expanded.has(key)}
              {@html ''}
              <div class="poll-voters">
                {#each demoVoters[opt.label] ?? [] as voter}
                  <span class="voter">{voter}</span>
                {:else}
                  <span style="color:var(--fg-faint);">Никто</span>
                {/each}
              </div>
              <button class="poll-expand collapse" onclick={() => toggleExpand(key)}>
                Свернуть
                <svg viewBox="0 0 24 24" class="ic-sm"><path d="M18 15l-6-6-6 6"/></svg>
              </button>
            {:else}
              <button class="poll-expand" onclick={() => toggleExpand(key)}>
                Кто проголосовал
                <svg viewBox="0 0 24 24" class="ic-sm"><path d="M6 9l6 6 6-6"/></svg>
              </button>
            {/if}
          {/each}
        </article>
      {/each}
    </div>
  {/if}
</MemberShell>

<style>
  .poll-expand {
    display: flex; align-items: center; gap: 4px;
    background: none; border: 0; cursor: pointer;
    font: inherit; font-size: 12px; color: var(--fg-mute);
    padding: 4px 14px; margin: -4px 0 8px;
  }
  .poll-expand:hover { color: var(--fg); }
  .poll-expand.collapse { color: var(--fg-faint); }
  .poll-expand:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
  .ic-sm { width: 14px; height: 14px; stroke: currentColor; fill: none; stroke-width: 1.7; }
</style>
