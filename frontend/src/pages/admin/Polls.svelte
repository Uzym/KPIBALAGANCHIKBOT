<script>
  import AdminShell from '../../components/AdminShell.svelte';
  import { api } from '../../lib/api.js';
  import { navigate } from '../../lib/router.js';

  let polls = [];
  let loading = true;
  let showCreate = false;
  let pollFilter = 'Все';
  let editingPoll = null; // null = не редактируем

  let formData = {
    question: '',
    options: ['', '', ''], // 3 пустых варианта для старта
    multichoice: false,
    deadline: '',
  };

  async function load() {
    polls = await api.getPolls();
    loading = false;
  }
  load();

  $: filtered = pollFilter === 'Все'
    ? polls
    : polls.filter(p => p.status === pollFilter);

  function toggleCreate() {
    showCreate = !showCreate;
    if (showCreate) {
      editingPoll = null;
      formData = { question: '', options: ['', '', ''], multichoice: false, deadline: '' };
    }
  }

  function startEdit(poll) {
    editingPoll = poll;
    showCreate = true;
    formData = {
      question: poll.question,
      options: poll.options.map(o => o.label),
      multichoice: poll.multi,
      deadline: poll.deadline || '',
    };
  }

  function addOption() {
    if (formData.options.length < 10) formData.options = [...formData.options, ''];
  }

  function removeOption(i) {
    if (formData.options.length > 2) {
      formData.options = formData.options.filter((_, idx) => idx !== i);
    }
  }

  async function submit(e) {
    e.preventDefault();
    const opts = formData.options.filter(o => o.trim());
    if (!formData.question.trim() || opts.length < 2) return;

    if (editingPoll) {
      await api.updatePoll(editingPoll.id, {
        question: formData.question,
        multichoice: formData.multichoice,
        options: opts,
      });
      await load();
    } else {
      await api.createPoll({
        question: formData.question,
        multichoice: formData.multichoice,
        options: opts,
      });
      await load();
    }
    toggleCreate();
  }

  async function closePoll(id) {
    await api.closePoll(id);
    await load();
  }

  async function reopenPoll(id) {
    await api.reopenPoll(id);
    await load();
  }

  async function cancelPoll(id) {
    await api.deletePoll(id);
    await load();
  }
</script>

<AdminShell title="Опросы">
  <div slot="actions">
    <button class="btn btn-primary btn-sm" onclick={toggleCreate}>
      {showCreate ? 'Скрыть' : 'Создать'}
    </button>
  </div>

  <!-- фильтр -->
  <div class="filter-row">
    {#each ['Все', 'open', 'closed'] as f}
      <button class="filter-chip" class:active={pollFilter === f}
              onclick={() => pollFilter = f}>
        {f === 'Все' ? 'Все' : f === 'open' ? 'Открытые' : 'Закрытые'}
      </button>
    {/each}
  </div>

  <!-- форма создания/редактирования -->
  {#if showCreate}
    <div class="card" style="margin-bottom:20px;">
      <p class="eyebrow" style="margin:0 0 14px;">
        {editingPoll ? 'Редактировать опрос' : 'Новый опрос'}
      </p>
      <form class="stack" style="gap:12px;" onsubmit={submit}>
        <div class="form-field">
          <label for="poll-q">Вопрос</label>
          <input id="poll-q" required bind:value={formData.question}
                 placeholder="Куда едем в декабре?">
        </div>

        <div class="stack" style="gap:8px;">
          <label style="font-size:var(--fs-small);font-weight:500;color:var(--fg-soft);">Варианты</label>
          {#each formData.options as opt, i}
            <div class="row" style="gap:8px;">
              <input class="opt-input" placeholder="Вариант {i + 1}"
                     bind:value={formData.options[i]}>
              {#if formData.options.length > 2}
                <button type="button" class="btn btn-ghost btn-sm"
                        onclick={() => removeOption(i)} aria-label="Убрать вариант {i + 1}">
                  <svg viewBox="0 0 24 24" style="width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:1.7;"><path d="M18 6L6 18M6 6l12 12"/></svg>
                </button>
              {/if}
            </div>
          {/each}
          {#if formData.options.length < 10}
            <button type="button" class="btn btn-secondary btn-sm" onclick={addOption}>
              + Добавить вариант
            </button>
          {/if}
        </div>

        <div class="row-between">
          <label for="poll-multi" style="font-size:14px;cursor:pointer;">
            Мультивыбор (несколько ответов)
          </label>
          <input id="poll-multi" type="checkbox" bind:checked={formData.multichoice}
                 style="width:20px;height:20px;cursor:pointer;">
        </div>

        <div class="form-field">
          <label for="poll-deadline">Срок (необязательно)</label>
          <input id="poll-deadline" type="date" bind:value={formData.deadline}>
        </div>

        <div class="row" style="gap:10px;">
          <button type="submit" class="btn btn-primary btn-sm" style="flex:1;">
            {editingPoll ? 'Сохранить' : 'Опубликовать'}
          </button>
          <button type="button" class="btn btn-secondary btn-sm" style="flex:1;"
                  onclick={toggleCreate}>Отмена</button>
        </div>
      </form>
    </div>
  {/if}

  <!-- список опросов -->
  {#if loading}
    <div class="skeleton" style="height:200px;border-radius:18px;"></div>
  {:else}
    {#each filtered as poll (poll.id)}
      <div class="card" style="margin-bottom:16px;">
        <div class="row-between" style="margin-bottom:10px;">
          <div>
            <h3 class="h3">{poll.question}</h3>
            <p class="meta" style="margin:4px 0 0;">
              {poll.multi ? 'Мультивыбор' : 'Один ответ'} · {poll.voted} проголосовало
              {#if poll.deadline} · до {poll.deadline}{/if}
            </p>
          </div>
          <span class="tag" class:status-open={poll.status === 'open'}
                class:status-closed={poll.status === 'closed'}>
            {poll.status === 'open' ? 'Открыт' : 'Закрыт'}
          </span>
        </div>

        <!-- результаты -->
        <div class="stack" style="gap:6px;margin-bottom:12px;">
          {#each poll.options as opt}
            <div class="row-between">
              <span style="font-size:14px;">{opt.label}</span>
              <div class="row" style="gap:8px;">
                <div class="progress" style="width:100px;">
                  <span style="width:{poll.voted ? Math.round(opt.count / poll.voted * 100) : 0}%;"></span>
                </div>
                <span class="num" style="font-weight:600;min-width:24px;text-align:right;">{opt.count}</span>
              </div>
            </div>
          {/each}
        </div>

        <!-- действия -->
        <div class="row" style="gap:8px;flex-wrap:wrap;">
          <button class="btn btn-secondary btn-sm" onclick={() => startEdit(poll)}>
            Изменить
          </button>
          {#if poll.status === 'open'}
            <button class="btn btn-secondary btn-sm" onclick={() => closePoll(poll.id)}>
              Закрыть
            </button>
          {:else}
            <button class="btn btn-secondary btn-sm" onclick={() => reopenPoll(poll.id)}>
              Открыть
            </button>
          {/if}
          <button class="btn btn-ghost btn-sm" onclick={() => cancelPoll(poll.id)}
                  style="color:var(--accent-dark);">
            Удалить
          </button>
        </div>
      </div>
    {:else}
      <div class="empty-state">
        <div class="icon-circle">
          <svg viewBox="0 0 24 24" style="width:28px;height:28px;stroke:currentColor;fill:none;stroke-width:1.5;"><path d="M18 6L9 13l-3-2-4 3"/><path d="M2 20h20"/></svg>
        </div>
        <h3>Нет опросов</h3>
        <p>Создай первый опрос кнопкой «Создать»</p>
      </div>
    {/each}
  {/if}
</AdminShell>

<style>
  .opt-input {
    flex: 1; padding: 10px 14px; border: 1px solid var(--border); border-radius: 10px;
    background: var(--surface); color: var(--fg); font: inherit; font-size: 14px; min-height: 44px;
  }
  .opt-input:focus-visible { outline: 2px solid var(--accent); outline-offset: 0; }
</style>
