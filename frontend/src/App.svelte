<script>
  import { path, navigate } from './lib/router.js';
  import { api } from './lib/api.js';

  // ── страницы участника ──
  import MemberAfisha from './pages/member/Afisha.svelte';
  import MemberPolls from './pages/member/Polls.svelte';
  import MemberFees from './pages/member/Fees.svelte';
  import MemberProfile from './pages/member/Profile.svelte';
  import MemberChat from './pages/member/Chat.svelte';

  // ── страницы руководителя ──
  import AdminDashboard from './pages/admin/Dashboard.svelte';
  import AdminEvents from './pages/admin/Events.svelte';
  import AdminPeople from './pages/admin/People.svelte';
  import AdminFees from './pages/admin/Fees.svelte';

  const routes = {
    '/': null,
    '/member': MemberAfisha,
    '/member/afisha': MemberAfisha,
    '/member/polls': MemberPolls,
    '/member/fees': MemberFees,
    '/member/profile': MemberProfile,
    '/member/chat': MemberChat,
    '/admin': AdminDashboard,
    '/admin/dashboard': AdminDashboard,
    '/admin/events': AdminEvents,
    '/admin/people': AdminPeople,
    '/admin/fees': AdminFees,
  };

  let currentPath = '';
  $: currentPath = $path;
  $: page = routes[currentPath] ?? null;
  $: isCover = currentPath === '/' || currentPath === '';
</script>

{#if isCover}
  <!-- ═══ Обложка ═══ -->
  <main class="cover">
    <div>
      <p class="eyebrow" style="justify-content:center;">КПИ · Сезон 2026/27</p>
      <h1 class="cover-title">Уютный <span class="it">Балаганчик</span></h1>
      <p class="cover-sub">События, запись, опросы, взносы — для участников и руководителей.</p>
    </div>
    <div class="cover-modes">
      <button class="mode-btn" onclick={() => navigate('/member')}>
        <span class="roman">I.</span>
        <span class="label">Участник</span>
        <span class="desc">Афиша, запись, опросы, взнос</span>
      </button>
      <button class="mode-btn" onclick={() => navigate('/admin')}>
        <span class="roman">II.</span>
        <span class="label">Руководитель</span>
        <span class="desc">Дашборд, события, люди, оплата</span>
      </button>
    </div>
  </main>
{:else if page}
  <svelte:component this={page} />
{/if}

<style>
  .cover {
    min-height: 100vh; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 40px; padding: 40px 20px;
  }
  .cover-title {
    font-family: var(--font-display); font-size: clamp(40px, 8vw, 72px);
    letter-spacing: -0.03em; line-height: 1.05; margin: 0; text-align: center;
  }
  .cover-title .it { font-style: italic; color: var(--accent); }
  .cover-sub { max-width: 48ch; text-align: center; color: var(--fg-mute); margin: 16px 0 0; }
  .cover-modes { display: flex; gap: 16px; flex-wrap: wrap; justify-content: center; }
  .mode-btn {
    display: flex; flex-direction: column; align-items: flex-start; gap: 8px;
    padding: 24px 32px; min-width: 240px;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius-lg); cursor: pointer; text-align: left;
    transition: transform var(--dur) var(--ease);
    font: inherit; color: var(--fg);
  }
  .mode-btn:hover { transform: translateY(-3px); box-shadow: 0 12px 30px -10px rgba(21,20,15,0.15); }
  .mode-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .mode-btn .roman { font-family: var(--font-display); font-style: italic; font-size: 14px; color: var(--accent); }
  .mode-btn .label { font-family: var(--font-display); font-size: 24px; font-weight: 600; }
  .mode-btn .desc { color: var(--fg-mute); font-size: var(--fs-small); }
</style>
