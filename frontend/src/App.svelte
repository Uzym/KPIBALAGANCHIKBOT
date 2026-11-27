<script>
  import { path, navigate } from './lib/router.js';
  import { user, authLoading, loginWithToken, logout } from './lib/auth.js';

  // ── страницы участника ──
  import MemberAfisha from './pages/member/Afisha.svelte';
  import MemberPolls from './pages/member/Polls.svelte';
  import MemberFees from './pages/member/Fees.svelte';
  import MemberProfile from './pages/member/Profile.svelte';
  import MemberChat from './pages/member/Chat.svelte';
  import MemberEventDetail from './pages/member/EventDetail.svelte';

  // ── страницы руководителя ──
  import AdminDashboard from './pages/admin/Dashboard.svelte';
  import AdminEvents from './pages/admin/Events.svelte';
  import AdminPeople from './pages/admin/People.svelte';
  import AdminFees from './pages/admin/Fees.svelte';
  import AdminPersonDetail from './pages/admin/PersonDetail.svelte';
  import AdminPolls from './pages/admin/Polls.svelte';

  const routes = {
    '/': null,
    '/member': MemberAfisha,
    '/member/afisha': MemberAfisha,
    '/member/polls': MemberPolls,
    '/member/fees': MemberFees,
    '/member/profile': MemberProfile,
    '/member/chat': MemberChat,
    '/member/event': MemberEventDetail,
    '/admin': AdminDashboard,
    '/admin/dashboard': AdminDashboard,
    '/admin/events': AdminEvents,
    '/admin/people': AdminPeople,
    '/admin/fees': AdminFees,
    '/admin/person': AdminPersonDetail,
    '/admin/polls': AdminPolls,
  };

  let currentPath = '';
  let loginToken = '';
  let loginError = '';
  let loginBusy = false;

  $: currentPath = $path;
  $: page = routes[currentPath]
    ?? (currentPath.startsWith('/member/event/') ? MemberEventDetail : null)
    ?? (currentPath.startsWith('/admin/person/') ? AdminPersonDetail : null);
  $: isCover = currentPath === '/' || currentPath === '';
  $: isAdmin = $user?.role === 'admin';
  $: isAuthRoute = currentPath.startsWith('/auth');

  // обработка /auth?t=token
  $: if (isAuthRoute && $authLoading === false && !$user) {
    const urlParams = new URLSearchParams(window.location.hash.split('?')[1] || '');
    const t = urlParams.get('t') || currentPath.split('/auth?t=').pop() || '';
    if (t && t !== loginToken && !loginBusy) {
      loginToken = t;
      doLogin(t);
    }
  }

  async function doLogin(token) {
    loginBusy = true;
    loginError = '';
    try {
      await loginWithToken(token);
      navigate('/member');
    } catch (e) {
      loginError = e.message;
    } finally {
      loginBusy = false;
    }
  }

  async function manualLogin(e) {
    e.preventDefault();
    if (!loginToken.trim()) return;
    // если вставили полную ссылку — вытащить токен
    let t = loginToken.trim();
    if (t.includes('t=')) {
      try { t = new URL(t).searchParams.get('t') || t.split('t=').pop(); } catch {}
    }
    await doLogin(t);
  }
</script>

{#if $authLoading}
  <!-- загрузка -->
  <main class="cover">
    <div class="loading-dots">
      <span></span><span></span><span></span>
    </div>
    <p class="meta" style="text-align:center;">Проверяю сессию…</p>
  </main>
{:else if !$user}
  <!-- ═══ Не авторизован: логин ═══ -->
  <main class="cover">
    <div>
      <p class="eyebrow" style="justify-content:center;">Клуб по интересам</p>
      <h1 class="cover-title">Уютный <span class="it">Балаганчик</span></h1>
    </div>

    <div class="login-card card">
      {#if loginBusy}
        <p style="text-align:center;color:var(--fg-mute);">Вхожу…</p>
      {:else if loginError}
        <p class="login-error">{loginError}</p>
        <form onsubmit={manualLogin}>
          <div class="form-field">
            <label for="token">Ссылка или токен</label>
            <input id="token" bind:value={loginToken} placeholder="Вставь ссылку из бота">
          </div>
          <button type="submit" class="btn btn-primary btn-sm" style="width:100%;">Войти</button>
        </form>
      {:else}
        <h3 style="font-family:var(--font-display);text-align:center;margin:0 0 8px;">Вход</h3>
        <p style="text-align:center;color:var(--fg-mute);font-size:14px;margin:0 0 16px;">
          Отправь <strong>/веб</strong> боту клуба в ВК —<br>
          он пришлёт ссылку для входа.
        </p>
        <div class="login-divider">или</div>
        <form onsubmit={manualLogin}>
          <div class="form-field">
            <label for="token">Вставь ссылку из бота</label>
            <input id="token" bind:value={loginToken} placeholder="https://votilya.ru:8450/auth?t=…">
          </div>
          <button type="submit" class="btn btn-primary btn-sm" style="width:100%;">Войти</button>
        </form>
      {/if}
    </div>
  </main>
{:else if isCover || isAuthRoute}
  <!-- ═══ Обложка (авторизован) ═══ -->
  <main class="cover">
    <div>
      <p class="eyebrow" style="justify-content:center;">Клуб по интересам</p>
      <h1 class="cover-title">Уютный <span class="it">Балаганчик</span></h1>
      <p class="user-greet">Привет, {$user.name}!</p>
    </div>
    <div class="cover-modes">
      <button class="mode-btn" onclick={() => navigate('/member')}>
        <span class="roman">I.</span>
        <span class="label">Участник</span>
        <span class="desc">Афиша, запись, опросы, взнос</span>
      </button>
      {#if isAdmin}
        <button class="mode-btn" onclick={() => navigate('/admin')}>
          <span class="roman">II.</span>
          <span class="label">Руководитель</span>
          <span class="desc">Дашборд, события, люди, оплата</span>
        </button>
      {/if}
    </div>
    <button class="btn btn-ghost btn-sm" onclick={logout}>Выйти</button>
  </main>
{:else if page}
  {#if currentPath.startsWith('/admin') && !isAdmin}
    <main class="cover">
      <div>
        <h1 class="cover-title" style="font-size:32px;">Нет доступа</h1>
        <p style="text-align:center;color:var(--fg-mute);">Раздел только для руководителей.</p>
        <button class="btn btn-secondary btn-sm" style="margin:16px auto;display:block;"
                onclick={() => navigate('/member')}>К афише</button>
      </div>
    </main>
  {:else}
    <svelte:component this={page} />
  {/if}
{/if}

<style>
  .cover {
    min-height: 100vh; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 32px; padding: 40px 20px;
  }
  .cover-title {
    font-family: var(--font-display); font-size: clamp(40px, 8vw, 72px);
    letter-spacing: -0.03em; line-height: 1.05; margin: 0; text-align: center;
  }
  .cover-title .it { font-style: italic; color: var(--accent); }
  .user-greet {
    text-align: center; font-size: 16px; color: var(--fg-mute); margin: 12px 0 0;
  }
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

  .login-card {
    max-width: 400px; width: 100%; padding: 28px;
  }
  .login-error {
    color: var(--accent-dark); font-size: 14px; text-align: center;
    padding: 8px; margin: 0 0 12px; background: rgba(178,59,46,0.08);
    border-radius: var(--radius);
  }
  .login-divider {
    text-align: center; color: var(--fg-faint); font-size: 12px;
    margin: 12px 0; position: relative;
  }
  .login-divider::before, .login-divider::after {
    content: ''; position: absolute; top: 50%; width: 35%; height: 1px;
    background: var(--border-light);
  }
  .login-divider::before { left: 0; }
  .login-divider::after { right: 0; }

  .loading-dots {
    display: flex; gap: 6px; justify-content: center;
  }
  .loading-dots span {
    width: 8px; height: 8px; border-radius: 50%; background: var(--accent);
    animation: bounce 1.2s infinite;
  }
  .loading-dots span:nth-child(2) { animation-delay: 0.2s; }
  .loading-dots span:nth-child(3) { animation-delay: 0.4s; }
  @keyframes bounce {
    0%, 60%, 100% { transform: translateY(0); }
    30% { transform: translateY(-8px); }
  }
</style>
