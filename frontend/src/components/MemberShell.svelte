<script>
  /** Каркас для страниц участника: верхняя панель + контент + таббар. */
  import { navigate, path } from '../lib/router.js';

  export let title = '';
  export let subtitle = '';

  const tabs = [
    { id: '/member', icon: 'calendar', label: 'Афиша' },
    { id: '/member/polls', icon: 'chart', label: 'Опросы' },
    { id: '/member/fees', icon: 'coin', label: 'Взнос' },
    { id: '/member/profile', icon: 'user', label: 'Профиль' },
  ];

  $: active = tabs.findIndex(t => t.id === $path);
</script>

<div class="shell">
  <header class="topbar">
    <button class="back" onclick={() => navigate('/')} aria-label="На обложку">
      <svg viewBox="0 0 24 24" class="ic"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
    </button>
    <span class="meta">Участник</span>
    <span class="meta">9:41</span>
  </header>

  <div class="page">
    {#if title}
      <div class="header">
        <div>
          {#if subtitle}<p class="greeting">{subtitle}</p>{/if}
          <h1 class="h1">{title}</h1>
        </div>
        <slot name="actions" />
      </div>
    {/if}
    <slot />
  </div>

  <nav class="tabbar" aria-label="Меню">
    {#each tabs as tab, i}
      <button class="tab" class:active={active === i} onclick={() => navigate(tab.id)}>
        <svg viewBox="0 0 24 24" class="ic">
          {#if tab.icon === 'calendar'}
            <rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>
          {:else if tab.icon === 'chart'}
            <path d="M18 6L9 13l-3-2-4 3"/><path d="M2 20h20"/>
          {:else if tab.icon === 'coin'}
            <circle cx="12" cy="12" r="9"/><path d="M12 7v10M15 9.5c0-1.4-1.3-2.5-3-2.5s-3 1-3 2.5c0 3 6 2 6 5 0 1.4-1.3 2.5-3 2.5s-3-1.1-3-2.5"/>
          {:else if tab.icon === 'user'}
            <circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-7 8-7s8 3 8 7"/>
          {/if}
        </svg>
        {tab.label}
      </button>
    {/each}
  </nav>
</div>

<style>
  .shell {
    max-width: 480px; margin: 0 auto; min-height: 100vh;
    display: flex; flex-direction: column;
  }
  .topbar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 12px 16px;
  }
  .topbar .back {
    background: none; border: 0; cursor: pointer; padding: 8px;
    border-radius: 50%; color: var(--fg-mute);
  }
  .topbar .back:hover { color: var(--fg); background: rgba(21,20,15,0.05); }
  .topbar .back:focus-visible { outline: 2px solid var(--accent); }
  .page { flex: 1; padding: 0 0 20px; overflow-y: auto; }
  .header {
    padding: 8px 20px 12px;
    display: flex; align-items: center; justify-content: space-between; gap: 12px;
  }
  .greeting {
    font-family: var(--font-mono); font-size: var(--fs-micro);
    letter-spacing: 0.08em; text-transform: uppercase;
    color: var(--fg-mute); margin: 0 0 4px;
  }
  .tabbar {
    display: grid; grid-template-columns: repeat(4, 1fr);
    padding: 8px 8px calc(8px + env(safe-area-inset-bottom, 0));
    border-top: 1px solid var(--border-light);
    background: color-mix(in srgb, var(--surface) 92%, transparent);
    backdrop-filter: blur(20px);
    position: sticky; bottom: 0;
  }
  .tab {
    display: flex; flex-direction: column; align-items: center; gap: 2px;
    padding: 8px 0; color: var(--fg-mute); font-size: 10px;
    background: none; border: 0; cursor: pointer; font-family: inherit;
  }
  .tab:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; border-radius: 8px; }
  .tab.active { color: var(--accent); }
  .tab .ic { width: 22px; height: 22px; stroke: currentColor; fill: none; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
  .tab.active .ic { stroke-width: 2; }
  .ic { width: 20px; height: 20px; stroke: currentColor; fill: none; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
</style>
