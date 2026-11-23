<script>
  /** Каркас для страниц руководителя: сайдбар (десктоп) / таббар (моб). */
  import { navigate, path } from '../lib/router.js';

  export let title = '';

  const items = [
    { id: '/admin', icon: 'grid', label: 'Дашборд' },
    { id: '/admin/events', icon: 'cal', label: 'События' },
    { id: '/admin/people', icon: 'users', label: 'Люди' },
    { id: '/admin/fees', icon: 'coin', label: 'Оплата' },
  ];

  $: active = items.findIndex(t => t.id === $path);

  function icon(svg) {
    if (svg === 'grid') return '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>';
    if (svg === 'cal') return '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>';
    if (svg === 'users') return '<circle cx="9" cy="8" r="3.5"/><path d="M2 20c0-3.5 3-6.5 7-6.5s7 3 7 6.5"/><circle cx="17" cy="9" r="2.5"/><path d="M16 14c3 0 6 2 6 6"/>';
    if (svg === 'coin') return '<circle cx="12" cy="12" r="9"/><path d="M12 7v10M15 9.5c0-1.4-1.3-2.5-3-2.5s-3 1-3 2.5c0 3 6 2 6 5 0 1.4-1.3 2.5-3 2.5s-3-1.1-3-2.5"/>';
    return '';
  }
</script>

<div class="admin-shell">
  <!-- сайдбар (десктоп) -->
  <aside class="sidebar">
    <div class="brand">
      <svg viewBox="0 0 24 24" class="ic"><path d="M3 4v16h18V4"/><path d="M3 8h18"/><path d="M12 4v4"/></svg>
      Балаганчик
    </div>
    {#each items as item, i}
      <button class="nav-item" class:active={active === i} onclick={() => navigate(item.id)}>
        <svg viewBox="0 0 24 24" class="ic">{@html icon(item.icon)}</svg>
        {item.label}
      </button>
    {/each}
    <div class="spacer"></div>
    <button class="exit" onclick={() => navigate('/')}>
      <svg viewBox="0 0 24 24" class="ic"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/></svg>
      Выйти
    </button>
  </aside>

  <!-- контент -->
  <main class="main">
    {#if title}
      <div class="main-header">
        <h1>{title}</h1>
        <div class="actions"><slot name="actions" /></div>
      </div>
    {/if}
    <slot />
  </main>

  <!-- таббар (моб) -->
  <nav class="tabbar" aria-label="Меню руководителя">
    {#each items as item, i}
      <button class="tab" class:active={active === i} onclick={() => navigate(item.id)}>
        <svg viewBox="0 0 24 24" class="ic">{@html icon(item.icon)}</svg>
        {item.label}
      </button>
    {/each}
  </nav>
</div>

<style>
  .admin-shell {
    display: flex; min-height: 100vh;
  }
  .sidebar {
    width: 220px; flex-shrink: 0;
    border-right: 1px solid var(--border-light);
    padding: 20px 12px;
    display: flex; flex-direction: column; gap: 4px;
    background: var(--surface-warm);
    position: sticky; top: 0; height: 100vh;
  }
  .brand {
    font-family: var(--font-display); font-style: italic;
    font-size: 18px; font-weight: 600; padding: 0 12px 16px;
    display: flex; align-items: center; gap: 8px; color: var(--fg);
  }
  .nav-item {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 14px; border-radius: 10px;
    color: var(--fg-mute); font-size: 14px; font-weight: 500;
    cursor: pointer; border: 0; background: none; text-align: left; width: 100%;
    font-family: inherit; transition: all var(--dur) var(--ease);
  }
  .nav-item:hover { color: var(--fg); background: rgba(21,20,15,0.04); }
  .nav-item:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .nav-item.active { color: var(--accent-dark); background: rgba(237,111,92,0.1); font-weight: 600; }
  .nav-item .ic { width: 18px; height: 18px; stroke: currentColor; fill: none; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
  .spacer { flex: 1; }
  .exit {
    padding: 10px 14px; color: var(--fg-faint); font-size: var(--fs-small);
    cursor: pointer; border: 0; background: none; text-align: left;
    display: flex; align-items: center; gap: 10px; font-family: inherit;
  }
  .exit:hover { color: var(--fg); }
  .exit .ic { width: 18px; height: 18px; stroke: currentColor; fill: none; stroke-width: 1.7; }

  .main { flex: 1; overflow-y: auto; padding: 28px 32px; }
  .main-header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 24px;
  }
  .main-header h1 {
    font-family: var(--font-display); font-size: 28px; font-weight: 700;
    letter-spacing: -0.025em; margin: 0; color: var(--fg);
  }
  .actions { display: flex; gap: 10px; }

  .tabbar { display: none; }

  @media (max-width: 768px) {
    .sidebar { display: none; }
    .tabbar {
      display: grid; grid-template-columns: repeat(4, 1fr);
      padding: 8px 8px calc(8px + env(safe-area-inset-bottom, 0));
      border-top: 1px solid var(--border-light);
      background: color-mix(in srgb, var(--surface) 92%, transparent);
      backdrop-filter: blur(20px);
      position: fixed; bottom: 0; left: 0; right: 0;
    }
    .tab {
      display: flex; flex-direction: column; align-items: center; gap: 2px;
      padding: 8px 0; color: var(--fg-mute); font-size: 10px;
      background: none; border: 0; cursor: pointer; font-family: inherit;
    }
    .tab.active { color: var(--accent); }
    .tab .ic { width: 22px; height: 22px; stroke: currentColor; fill: none; stroke-width: 1.7; }
    .main { padding: 20px 16px 90px; }
  }
</style>
