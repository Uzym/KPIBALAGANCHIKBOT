<script>
  import MemberShell from '../../components/MemberShell.svelte';
  import { api } from '../../lib/api.js';
  import { navigate } from '../../lib/router.js';

  let profile = null;
  let loading = true;
  let announcementsOn = true;

  async function load() {
    profile = await api.getProfile();
    announcementsOn = profile?.settings?.announcements ?? true;
    loading = false;
  }
  load();

  function toggleAnnouncements() {
    announcementsOn = !announcementsOn;
    // TODO: отправить на API
  }
  load();
</script>

<MemberShell title={profile?.name ?? 'Профиль'} subtitle="Твой профиль">
  {#if loading}
    <div class="pad"><div class="skeleton" style="height:200px;border-radius:18px;"></div></div>
  {:else}
    <div class="pad stack" style="gap:12px;">
      <!-- чат с руководителем -->
      <article class="card clickable" role="link" tabindex="0"
               onclick={() => navigate('/member/chat')}
               onkeydown={e => e.key === 'Enter' && navigate('/member/chat')}
               aria-label="Написать руководителю">
        <div class="row">
          <svg class="ic" viewBox="0 0 24 24"><path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5c-1.5 0-3-.4-4.2-1.1L3 20l1.1-5.3A8.5 8.5 0 1 1 21 11.5z"/></svg>
          <div style="flex:1;">
            <div class="h3">Написать руководителю</div>
            <p class="meta" style="margin:2px 0 0;">Прямое сообщение</p>
          </div>
          <svg class="ic" viewBox="0 0 24 24"><path d="M9 18l6-6-6-6"/></svg>
        </div>
      </article>

      <!-- аккаунты -->
      <article class="card">
        <p class="eyebrow" style="margin:0 0 10px;">Аккаунты</p>
        <div class="stack" style="gap:10px;">
          <div class="row-between">
            <span style="font-size:14px;">ВКонтакте</span>
            <span class="tag status-open">Связан</span>
          </div>
          <div class="row-between">
            <span style="font-size:14px;">Telegram</span>
            <span class="tag status-open">Связан</span>
          </div>
        </div>
        <p class="meta" style="margin:10px 0 0;">Связанные аккаунты = один голос</p>
      </article>

      <!-- настройки -->
      <article class="card">
        <p class="eyebrow" style="margin:0 0 10px;">Настройки</p>
        <div class="list-row" style="grid-template-columns:1fr auto;">
          <div class="body">
            <div class="title">Объявления в личку</div>
            <div class="sub">В беседе видно всегда</div>
          </div>
          <button class="toggle" class:on={announcementsOn} role="switch"
                  aria-checked={announcementsOn}
                  aria-label="Объявления в личку"
                  onclick={toggleAnnouncements}></button>
        </div>
      </article>
    </div>
  {/if}
</MemberShell>

<style>
  .clickable { cursor:pointer; transition:transform var(--dur) var(--ease); }
  .clickable:hover { transform:translateY(-2px); }
  .clickable:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
  .ic { width:20px; height:20px; stroke:currentColor; fill:none; stroke-width:1.7; stroke-linecap:round; stroke-linejoin:round; flex-shrink:0; }
</style>
