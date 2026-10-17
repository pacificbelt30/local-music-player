import { api } from "./api.js";
import { oauthStatusLines, connectionGuide } from "./oauth-status.js";

const accountPlaylists = new Map();
const accountRows = new Map();
const syncRecords = new Map();
const syncCards = new Map();
const trackRequests = new WeakMap();
let accountListRequest = 0;
let syncListRequest = 0;
let lastAddedSyncId = null;

function feedback(id, message = "", error = false) {
  const element = document.getElementById(id);
  if (!element) return;
  element.textContent = message;
  element.classList.toggle("error-msg", error);
}

function reconcileRows(container, rows, selector, emptyMessage) {
  const keep = new Set(rows);
  for (const child of [...container.children]) {
    if (!child.matches(selector) || !keep.has(child)) child.remove();
  }
  let cursor = container.firstElementChild;
  for (const row of rows) {
    if (row === cursor) cursor = cursor.nextElementSibling;
    else container.insertBefore(row, cursor);
  }
  if (!rows.length) container.innerHTML = `<div class="empty-state">${escHtml(emptyMessage)}</div>`;
}

function invalidateSyncRequests() {
  syncListRequest++;
  document.getElementById("yt-sync-list")?.removeAttribute("aria-busy");
  feedback("yt-sync-list-status");
}

function resetAccountPlaylists() {
  accountListRequest++;
  accountPlaylists.clear();
  accountRows.clear();
  document.getElementById("yt-account-playlists")?.replaceChildren();
  feedback("yt-account-status");
}

export function initPlaylists() {
  // Handle youtube_auth=success redirect from OAuth callback
  if (new URLSearchParams(location.search).get("youtube_auth") === "success") {
    history.replaceState({}, "", "/");
  }
  document.getElementById("yt-dismiss-add-result")?.addEventListener("click", clearAddResult);
  document.getElementById("yt-view-added-sync")?.addEventListener("click", () => {
    const card = syncCards.get(lastAddedSyncId);
    if (!card?.isConnected) {
      document.getElementById("yt-sync-add-message").textContent = "追加した同期は一覧にありません。更新して確認してください。";
      return;
    }
    card.scrollIntoView?.({behavior: "smooth", block: "center"});
    card.querySelector(".yt-sync-detail-btn").focus({preventScroll: true});
  });
  renderAuthSection();
  renderUrlSyncSection();
  renderSyncList();
  document.getElementById("yt-refresh-account-btn")?.addEventListener("click", renderAccountPlaylists);
  document.getElementById("yt-refresh-syncs-btn")?.addEventListener("click", renderSyncList);
}

function clearAddResult() {
  const notice = document.getElementById("yt-sync-add-result");
  if (notice) notice.hidden = true;
}

function showAddResult(sync) {
  lastAddedSyncId = String(sync.id);
  const notice = document.getElementById("yt-sync-add-result");
  if (!notice) return;
  document.getElementById("yt-sync-add-message").textContent = `「${sync.playlist_name}」の同期を追加しました`;
  notice.hidden = false;
  for (const [id, card] of syncCards) card.classList.toggle("just-added", id === lastAddedSyncId);
}

// ── Auth Section ──────────────────────────────────────────────────────────────

async function renderAuthSection() {
  const container = document.getElementById("yt-auth-section");
  if (!container) return;

  try {
    const status = await api.youtubeAuthStatus();
    displayConnectionGuide(status);
    if (status.authenticated) {
      container.innerHTML = `
        <div class="yt-auth-connected">
          <span class="status-badge" id="yt-auth-badge"></span>
          <button class="btn btn-ghost" id="yt-auth-check-btn">接続を確認</button>
          <button class="btn btn-primary" id="yt-reauth-btn">再認証（OAuth）</button>
          <button class="btn btn-ghost" id="yt-token-toggle-btn">トークンを直接入力</button>
          <button class="btn btn-ghost" id="yt-disconnect-btn">接続解除</button>
        </div>
        <div id="yt-oauth-status" class="yt-list-feedback" role="status" aria-live="polite"></div>
        ${tokenFormHTML()}
      `;
      displayOAuthStatus(status);
      document.getElementById("yt-auth-check-btn").addEventListener("click", async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        button.textContent = "確認中…";
        try { displayOAuthStatus(await api.youtubeAuthCheck()); }
        catch (error) { displayConnectionGuide(null); feedback("yt-oauth-status", "確認に失敗しました: " + error.message, true); }
        finally { button.disabled = false; button.textContent = "接続を確認"; }
      });
      document.getElementById("yt-reauth-btn").addEventListener("click", connectYouTube);
      document.getElementById("yt-disconnect-btn").addEventListener("click", disconnectYouTube);
      bindTokenForm();
      document.getElementById("yt-playlist-picker").style.display = "";
      renderAccountPlaylists();
    } else {
      container.innerHTML = `
        <div class="yt-auth-disconnected">
          <p class="yt-auth-hint">YouTubeアカウントに接続してプレイリストを同期できます。</p>
          <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
            <button class="btn btn-primary" id="yt-connect-btn">YouTubeアカウントに接続</button>
            <button class="btn btn-ghost" id="yt-token-toggle-btn">トークンを直接入力</button>
          </div>
          ${tokenFormHTML()}
        </div>
      `;
      document.getElementById("yt-connect-btn").addEventListener("click", connectYouTube);
      bindTokenForm();
      document.getElementById("yt-playlist-picker").style.display = "none";
    }
  } catch (e) {
    displayConnectionGuide(null);
    container.innerHTML = `<div class="error-msg">${escHtml(e.message)}</div>`;
  }
}

function displayConnectionGuide(status) {
  const guide = connectionGuide(status);
  const message = document.getElementById("yt-connection-guide-message");
  const action = document.getElementById("yt-connection-guide-action");
  if (message) message.textContent = guide.message;
  if (action) { action.textContent = guide.action; action.hidden = false; }
}

function displayOAuthStatus(status) {
  displayConnectionGuide(status);
  const badge = document.getElementById("yt-auth-badge");
  if (!badge) return;
  const problem = ["reauth_required", "configuration_error", "temporary_error", "check_required"].includes(status.refresh_status);
  badge.textContent = !status.authenticated ? "YouTube未接続" : status.refresh_status === "reauth_required" ? "YouTube再認証が必要" : problem ? "YouTube接続を確認" : "YouTube認証情報あり";
  badge.classList.toggle("status-complete", status.authenticated && !problem);
  const box = document.getElementById("yt-oauth-status");
  box.replaceChildren(...oauthStatusLines(status).map(line => {
    const element = document.createElement("div");
    element.textContent = line;
    return element;
  }));
}

async function refreshOAuthStatus() {
  try { displayOAuthStatus(await api.youtubeAuthStatus()); } catch (_) { displayConnectionGuide(null); }
}

function tokenFormHTML() {
  return `
    <div id="yt-token-form" style="display:none;margin-top:12px">
      <p class="yt-auth-hint" style="margin-bottom:8px">
        トークンは
        <a href="https://developers.google.com/oauthplayground/" target="_blank" rel="noopener">Google OAuth 2.0 Playground</a>
        で取得できます。Scope に
        <code>https://www.googleapis.com/auth/youtube</code>（非公開→限定公開の切替も行う場合）
        または <code>https://www.googleapis.com/auth/youtube.readonly</code>（読み取りのみ）を指定してください。
      </p>
      <div style="margin-bottom:6px">
        <label style="display:block;font-size:0.85em;margin-bottom:4px">Access Token <span style="opacity:.6">（必須）</span></label>
        <textarea id="yt-access-token-input" rows="3" style="width:100%;box-sizing:border-box;font-family:monospace;font-size:0.8em" placeholder="ya29.xxxxxx..."></textarea>
      </div>
      <div style="margin-bottom:6px">
        <label style="display:block;font-size:0.85em;margin-bottom:4px">Refresh Token <span style="opacity:.6">（任意 — client_id/secret 設定済みの場合に自動更新）</span></label>
        <textarea id="yt-refresh-token-input" rows="2" style="width:100%;box-sizing:border-box;font-family:monospace;font-size:0.8em" placeholder="1//xxxxxx..."></textarea>
      </div>
      <div style="margin-bottom:10px">
        <label style="display:block;font-size:0.85em;margin-bottom:4px">有効期限（秒） <span style="opacity:.6">（デフォルト: 3600）</span></label>
        <input id="yt-expires-in-input" type="number" value="3600" min="60" style="width:120px">
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-primary" id="yt-token-submit-btn">保存</button>
        <button class="btn btn-ghost" id="yt-token-cancel-btn">キャンセル</button>
      </div>
    </div>
  `;
}

function bindTokenForm() {
  document.getElementById("yt-token-toggle-btn").addEventListener("click", () => {
    const form = document.getElementById("yt-token-form");
    form.style.display = form.style.display === "none" ? "" : "none";
  });
  document.getElementById("yt-token-cancel-btn").addEventListener("click", () => {
    document.getElementById("yt-token-form").style.display = "none";
  });
  document.getElementById("yt-token-submit-btn").addEventListener("click", submitTokenDirectly);
}

async function connectYouTube() {
  try {
    const { url } = await api.youtubeAuthUrl();
    window.location.href = url;
  } catch (e) {
    alert("接続URLの取得に失敗しました: " + e.message);
  }
}

async function submitTokenDirectly() {
  const access_token = document.getElementById("yt-access-token-input").value.trim();
  const refresh_token = document.getElementById("yt-refresh-token-input").value.trim();
  const expires_in = parseInt(document.getElementById("yt-expires-in-input").value, 10) || 3600;
  if (!access_token) {
    alert("Access Token を入力してください");
    return;
  }
  const btn = document.getElementById("yt-token-submit-btn");
  btn.disabled = true;
  btn.textContent = "保存中…";
  try {
    await api.youtubeSetToken({ access_token, refresh_token, expires_in });
    resetAccountPlaylists();
    renderAuthSection();
    renderSyncList();
  } catch (e) {
    btn.disabled = false;
    btn.textContent = "保存";
    alert("トークンの保存に失敗しました: " + e.message);
  }
}

async function disconnectYouTube() {
  if (!confirm("YouTubeアカウントの接続を解除しますか？")) return;
  try {
    await api.youtubeRevokeAuth();
    resetAccountPlaylists();
    renderAuthSection();
  } catch (e) {
    alert("解除に失敗しました: " + e.message);
  }
}

// ── URL-based Sync Section ────────────────────────────────────────────────────

function renderUrlSyncSection() {
  const container = document.getElementById("yt-url-sync-section");
  if (!container) return;
  container.innerHTML = `
    <p class="yt-auth-hint">YouTubeプレイリストの共有URLを貼り付けて同期を追加（認証不要）。</p>
    <div class="yt-url-sync-row">
      <input type="url" id="yt-playlist-url-input" class="yt-url-input"
             placeholder="https://www.youtube.com/playlist?list=PLxxxx">
      <select id="yt-url-format" class="yt-url-select">${formatOptionsHTML()}</select>
      <select id="yt-url-quality" class="yt-url-select">
        <option value="192">192 kbps</option>
        <option value="320">320 kbps</option>
        <option value="best">Best</option>
      </select>
      <button class="btn btn-primary" id="yt-add-url-btn">同期追加</button>
    </div>
    <div id="yt-add-url-error" class="error-msg" style="display:none"></div>
  `;
  document.getElementById("yt-add-url-btn").addEventListener("click", addSyncFromUrl);
  document.getElementById("yt-playlist-url-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") addSyncFromUrl();
  });
}

async function addSyncFromUrl() {
  const urlInput = document.getElementById("yt-playlist-url-input");
  const url = urlInput.value.trim();
  const audio_format = document.getElementById("yt-url-format").value;
  const audio_quality = document.getElementById("yt-url-quality").value;
  const errDiv = document.getElementById("yt-add-url-error");
  const btn = document.getElementById("yt-add-url-btn");

  errDiv.style.display = "none";
  clearAddResult();
  if (!url) {
    errDiv.textContent = "URLを入力してください";
    errDiv.style.display = "";
    return;
  }

  btn.disabled = true;
  btn.textContent = "解析中…";
  try {
    invalidateSyncRequests();
    const sync = await api.youtubeCreateSync({ source_type: "url", source_url: url, audio_format, audio_quality });
    invalidateSyncRequests();
    applySync(sync);
    showAddResult(sync);
    urlInput.value = "";
    renderSyncList();
  } catch (e) {
    errDiv.textContent = e.message;
    errDiv.style.display = "";
  } finally {
    btn.disabled = false;
    btn.textContent = "同期追加";
  }
}

// ── Account Playlists Picker ──────────────────────────────────────────────────

async function renderAccountPlaylists() {
  const container = document.getElementById("yt-account-playlists");
  if (!container) return;
  const request = ++accountListRequest;
  container.setAttribute("aria-busy", "true");
  feedback("yt-account-status", accountRows.size ? "プレイリストを更新中…" : "");
  if (!accountRows.size) container.innerHTML = '<div class="empty-state">プレイリスト読込中…</div>';
  try {
    const playlists = await api.youtubeListAccountPlaylists();
    if (request !== accountListRequest) return;
    if (!Array.isArray(playlists)) throw new Error("プレイリストを取得できませんでした");
    const rows = [];
    const ids = new Set();
    for (const pl of playlists) {
      const id = String(pl.playlist_id);
      ids.add(id);
      accountPlaylists.set(id, pl);
      let item = accountRows.get(id);
      if (!item) {
        item = document.createElement("div");
        item.className = "yt-pl-item";
        item.dataset.playlistId = id;
        item.innerHTML = '<div class="yt-pl-art"></div><div class="yt-pl-info"><div class="yt-pl-title"></div><div class="yt-pl-meta-row"></div></div><button class="btn yt-add-sync-btn"></button>';
        const button = item.querySelector(".yt-add-sync-btn");
        button.addEventListener("click", () => showAddSyncDialog(button));
        accountRows.set(id, item);
      }
      updateAccountRow(item, pl);
      rows.push(item);
    }
    for (const id of accountRows.keys()) {
      if (!ids.has(id)) { accountRows.delete(id); accountPlaylists.delete(id); }
    }
    reconcileRows(container, rows, ".yt-pl-item", "プレイリストが見つかりません");
    feedback("yt-account-status");
  } catch (e) {
    if (request !== accountListRequest) return;
    feedback("yt-account-status", `更新に失敗しました: ${e.message}`, true);
    if (!accountRows.size) container.innerHTML = '<div class="empty-state">プレイリストを取得できませんでした</div>';
  } finally {
    if (request === accountListRequest) { container.removeAttribute("aria-busy"); refreshOAuthStatus(); }
  }
}

function updateAccountRow(item, pl) {
  const already = [...syncRecords.values()].some(sync => sync.playlist_id === pl.playlist_id);
  const duration = formatPlaylistDuration(pl.total_duration_secs);
  const art = item.querySelector(".yt-pl-art");
  if (art.dataset.thumbnail !== (pl.thumbnail_url || "")) {
    art.innerHTML = pl.thumbnail_url ? `<img class="yt-pl-thumb" src="${escHtml(pl.thumbnail_url)}" alt="" loading="lazy">` : '<div class="track-thumb-placeholder">▶</div>';
    art.dataset.thumbnail = pl.thumbnail_url || "";
  }
  item.querySelector(".yt-pl-title").textContent = pl.title;
  item.querySelector(".yt-pl-meta-row").innerHTML = `
    <span class="yt-pl-meta-badge">${pl.item_count} 曲</span>
    ${pl.privacy_status ? `<span class="yt-pl-meta-badge">${escHtml(privacyLabel(pl.privacy_status))}</span>` : ""}
    ${already ? '<span class="yt-pl-meta-badge">同期中</span>' : ""}
    ${duration ? `<span class="yt-pl-meta">総再生時間: ${escHtml(duration)}</span>` : ""}`;
  const button = item.querySelector(".yt-add-sync-btn");
  button.dataset.id = pl.playlist_id;
  button.dataset.name = pl.title;
  button.dataset.privacy = pl.privacy_status || "";
  button.classList.toggle("btn-primary", !already);
  button.classList.toggle("btn-ghost", already);
  if (!button.dataset.busy) button.textContent = already ? "+ 別形式で同期" : "+ 同期追加";
}

function updateAccountSyncBadges() {
  const records = [...syncRecords.values()];
  for (const [id, value] of [["sync-total", records.length], ["sync-enabled", records.filter(s => s.enabled).length], ["sync-errors", records.filter(s => s.last_error).length]]) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  }
  for (const [id, item] of accountRows) updateAccountRow(item, accountPlaylists.get(id));
}

function updatePlaylistPrivacy(id, privacy) {
  const playlist = accountPlaylists.get(String(id));
  if (!playlist) return;
  accountListRequest++;
  document.getElementById("yt-account-playlists")?.removeAttribute("aria-busy");
  feedback("yt-account-status");
  accountPlaylists.set(String(id), {...playlist, privacy_status: privacy});
  updateAccountRow(accountRows.get(String(id)), accountPlaylists.get(String(id)));
}

function privacyLabel(privacy) {
  return { private: "非公開", unlisted: "限定公開", public: "公開" }[privacy] || privacy || "不明";
}

function formatPlaylistDuration(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds)) || seconds <= 0) return null;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}時間${m}分`;
  return `${m}分`;
}

async function createUrlSyncWithRetry(playlistId, audio_format, audio_quality, btn) {
  const source_url = `https://www.youtube.com/playlist?list=${playlistId}`;
  const delaysMs = [3000, 5000, 8000]; // total ~16s of backoff after the first attempt
  for (let attempt = 0; ; attempt++) {
    try {
      return await api.youtubeCreateSync({ source_type: "url", source_url, audio_format, audio_quality });
    } catch (e) {
      if (attempt >= delaysMs.length) throw e;
      btn.textContent = `限定公開への反映待ち…(${attempt + 1}/${delaysMs.length})`;
      await new Promise((r) => setTimeout(r, delaysMs[attempt]));
    }
  }
}

// ── Add Sync Dialog ───────────────────────────────────────────────────────────

function showAddSyncDialog(btn) {
  const existing = document.getElementById("yt-add-sync-dialog");
  if (existing) existing.remove();

  const privacy = btn.dataset.privacy || "";
  const isPrivate = privacy === "private";

  // Private playlists can't be reached by a share URL unless switched to
  // unlisted first; public/unlisted ones can use the share URL right away.
  let methodSectionHTML;
  if (isPrivate) {
    methodSectionHTML = `
      <p class="yt-auth-hint" style="margin-bottom:8px">
        このプレイリストは<strong>非公開</strong>です。非公開のままYouTube APIで毎回同期できますが、
        <strong>限定公開に切り替えて共有URLを使う方式</strong>（以降はAPIを使わずに同期）にすることもできます。
      </p>
      <div class="yt-sync-method" style="margin-bottom:8px">
        <label style="display:block;margin-bottom:4px">
          <input type="radio" name="yt-sync-method" value="api" checked>
          API同期（非公開のまま・毎回API取得）
        </label>
        <label style="display:block">
          <input type="radio" name="yt-sync-method" value="url-switch">
          限定公開に切り替えて共有リンク同期（API節約）
        </label>
      </div>
    `;
  } else {
    methodSectionHTML = `
      <p class="yt-auth-hint" style="margin-bottom:8px">
        このプレイリストは<strong>${escHtml(privacyLabel(privacy))}</strong>です。
        共有URL経由でアクセスする方式（API不要）にしますか？
      </p>
      <div class="yt-sync-method" style="margin-bottom:8px">
        <label style="display:block;margin-bottom:4px">
          <input type="radio" name="yt-sync-method" value="url" checked>
          共有リンク同期（API不要・推奨）
        </label>
        <label style="display:block">
          <input type="radio" name="yt-sync-method" value="api">
          API同期（毎回API取得）
        </label>
      </div>
    `;
  }

  const dialog = document.createElement("div");
  dialog.id = "yt-add-sync-dialog";
  dialog.className = "yt-add-sync-dialog";
  dialog.innerHTML = `
    <div class="yt-add-sync-dialog-inner">
      <div class="yt-add-sync-dialog-title">同期設定: ${escHtml(btn.dataset.name)}</div>
      ${methodSectionHTML}
      <div class="format-row" style="margin-bottom:8px">
        <select id="yt-sync-format">${formatOptionsHTML()}</select>
        <select id="yt-sync-quality">
          <option value="192">192 kbps</option>
          <option value="320">320 kbps</option>
          <option value="best">Best</option>
        </select>
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-primary" id="yt-sync-confirm-btn" style="flex:1">同期追加</button>
        <button class="btn btn-ghost" id="yt-sync-cancel-btn">キャンセル</button>
      </div>
    </div>
  `;

  // Position near button
  document.body.appendChild(dialog);

  document.getElementById("yt-sync-cancel-btn").addEventListener("click", () => dialog.remove());
  document.getElementById("yt-sync-confirm-btn").addEventListener("click", async () => {
    const audio_format = document.getElementById("yt-sync-format").value;
    const audio_quality = document.getElementById("yt-sync-quality").value;
    const method = dialog.querySelector('input[name="yt-sync-method"]:checked').value;
    dialog.remove();
    btn.disabled = true;
    btn.dataset.busy = "true";
    btn.textContent = "追加中…";
    clearAddResult();
    try {
      invalidateSyncRequests();
      let sync;
      if (method === "api") {
        sync = await api.youtubeCreateSync({
          playlist_id: btn.dataset.id,
          playlist_name: btn.dataset.name,
          audio_format,
          audio_quality,
        });
      } else if (method === "url-switch") {
        // Flip the private playlist to unlisted, then resolve it by share URL.
        // YouTube's privacy change can take a few seconds to propagate to the
        // anonymous page yt-dlp scrapes, so retry instead of failing on the
        // first "playlist does not exist" while it's still catching up.
        await api.youtubeSetPlaylistPrivacy(btn.dataset.id, "unlisted");
        updatePlaylistPrivacy(btn.dataset.id, "unlisted");
        sync = await createUrlSyncWithRetry(btn.dataset.id, audio_format, audio_quality, btn);
      } else {
        // "url": sync via the playlist's share URL (no API).
        sync = await api.youtubeCreateSync({
          source_type: "url",
          source_url: `https://www.youtube.com/playlist?list=${btn.dataset.id}`,
          audio_format,
          audio_quality,
        });
      }
      invalidateSyncRequests();
      applySync(sync);
      showAddResult(sync);
      feedback("yt-account-status", "同期を追加しました");
      renderSyncList();
    } catch (e) {
      feedback("yt-account-status", "追加に失敗しました: " + e.message, true);
    } finally {
      btn.disabled = false;
      delete btn.dataset.busy;
      updateAccountSyncBadges();
    }
  });
}

// ── Sync List ─────────────────────────────────────────────────────────────────

async function renderSyncList() {
  const container = document.getElementById("yt-sync-list");
  if (!container) return;
  const request = ++syncListRequest;
  container.setAttribute("aria-busy", "true");
  feedback("yt-sync-list-status", syncCards.size ? "同期情報を更新中…" : "");
  try {
    const syncs = await api.youtubeListSyncs();
    if (request !== syncListRequest) return;
    if (!Array.isArray(syncs)) throw new Error("同期一覧を取得できませんでした");
    const ids = new Set(syncs.map(sync => String(sync.id)));
    for (const sync of syncs) {
      upsertSyncCard(sync);
    }
    for (const id of syncCards.keys()) {
      if (!ids.has(id)) { syncCards.delete(id); syncRecords.delete(id); }
    }
    reconcileRows(container, syncs.map(sync => syncCards.get(String(sync.id))), ".yt-sync-card", "同期中のプレイリストはありません");
    updateAccountSyncBadges();
    feedback("yt-sync-list-status");
  } catch (e) {
    if (request !== syncListRequest) return;
    feedback("yt-sync-list-status", `更新に失敗しました: ${e.message}`, true);
  } finally {
    if (request === syncListRequest) container.removeAttribute("aria-busy");
  }
}

function upsertSyncCard(sync) {
  if (sync?.id == null || typeof sync.audio_format !== "string") throw new Error("同期情報を取得できませんでした");
  const id = String(sync.id);
  syncRecords.set(id, sync);
  let card = syncCards.get(id);
  if (!card) {
    card = document.createElement("div");
    card.className = "yt-sync-card";
    card.dataset.syncId = id;
    card.innerHTML = syncCardHTML(sync);
    prepareSyncDetails(card, sync);
    bindSyncCardEvents(card, sync);
    syncCards.set(id, card);
  }
  updateSyncCard(card, sync);
  return card;
}

function applySync(sync) {
  upsertSyncCard(sync);
  const container = document.getElementById("yt-sync-list");
  reconcileRows(container, [...syncCards.values()], ".yt-sync-card", "同期中のプレイリストはありません");
  updateAccountSyncBadges();
}

function setCardMutation(card, pending) {
  if (pending) card.dataset.mutating = "true";
  else delete card.dataset.mutating;
  for (const selector of [".yt-sync-now-btn", ".yt-sync-toggle-btn", ".yt-sync-delete-btn"]) {
    const button = card.querySelector(selector);
    button.disabled = pending || Boolean(button.dataset.busy);
  }
}

function updateSyncCard(card, sync) {
  card.querySelector(".yt-sync-name").textContent = sync.playlist_name;
  card.querySelector(".sync-detail-title").textContent = sync.playlist_name;
  const state = card.querySelector(".yt-sync-state");
  state.textContent = sync.last_error ? "要対応" : sync.enabled ? "自動同期 有効" : "一時停止中";
  state.classList.toggle("needs-attention", Boolean(sync.last_error));
  const source = card.querySelector(".yt-sync-source");
  source.textContent = sync.source_type === "url" ? "共有URL同期" : "API同期";
  source.classList.toggle("status-complete", sync.source_type !== "url");
  const lastSynced = sync.last_synced ? new Date(sync.last_synced).toLocaleString("ja-JP") : "未同期";
  const progress = sync.track_count ? `${sync.downloaded_count}/${sync.track_count} 曲ダウンロード済み` : "トラックなし";
  card.querySelector(".yt-sync-progress").textContent = `${progress} · 最終同期: ${lastSynced}`;
  card.querySelector(".yt-sync-format").textContent = ["mp4", "webm"].includes(sync.audio_format)
    ? `${sync.audio_format.toUpperCase()} (動画)`
    : `${sync.audio_format.toUpperCase()} / ${sync.audio_quality === "best" ? "Best" : sync.audio_quality + "kbps"}`;
  const toggle = card.querySelector(".yt-sync-toggle-btn");
  toggle.dataset.enabled = String(sync.enabled);
  if (!toggle.dataset.busy) toggle.textContent = sync.enabled ? "一時停止" : "再開";
  const errors = card.querySelector(".yt-sync-error-section");
  const text = errors.querySelector(".yt-sync-error-text");
  if (!sync.last_error) errors.replaceChildren();
  else if (text) text.textContent = sync.last_error;
  else errors.innerHTML = `
    <div class="yt-sync-error-banner"><span class="yt-sync-error-icon">⚠</span><span class="yt-sync-error-summary">同期エラーが発生しました</span>
      <button class="btn btn-ghost yt-sync-error-detail-btn" data-id="${sync.id}">詳細を見る ▾</button></div>
    <div class="yt-sync-error-detail" id="yt-sync-error-${sync.id}" style="display:none"><pre class="yt-sync-error-text">${escHtml(sync.last_error)}</pre></div>`;
}

function syncCardHTML(sync) {
  const lastSynced = sync.last_synced
    ? new Date(sync.last_synced).toLocaleString("ja-JP")
    : "未同期";
  const progress = sync.track_count
    ? `${sync.downloaded_count}/${sync.track_count} 曲ダウンロード済み`
    : "トラックなし";

  const errorBanner = sync.last_error ? `
    <div class="yt-sync-error-banner">
      <span class="yt-sync-error-icon">⚠</span>
      <span class="yt-sync-error-summary">同期エラーが発生しました</span>
      <button class="btn btn-ghost yt-sync-error-detail-btn" data-id="${sync.id}">詳細を見る ▾</button>
    </div>
    <div class="yt-sync-error-detail" id="yt-sync-error-${sync.id}" style="display:none">
      <pre class="yt-sync-error-text">${escHtml(sync.last_error)}</pre>
    </div>
  ` : "";

  const sourceLabel = sync.source_type === "url" ? "共有URL同期" : "API同期";
  const sourceBadgeClass = sync.source_type === "url" ? "status-badge" : "status-badge status-complete";

  return `
    <div class="yt-sync-header">
      <div class="yt-sync-info">
        <div class="yt-sync-title">
          <span class="yt-id-badge" title="同期ID（DB障害メッセージの id= と一致）">ID:${sync.id}</span>
          <span class="yt-sync-name">${escHtml(sync.playlist_name)}</span>
          <span class="${sourceBadgeClass} yt-sync-source" style="font-size:0.7em">${sourceLabel}</span>
        </div>
        <div class="yt-sync-meta yt-sync-progress">${progress} · 最終同期: ${lastSynced}</div>
        <div class="yt-sync-meta yt-sync-format">${["mp4", "webm"].includes(sync.audio_format)
          ? `${sync.audio_format.toUpperCase()} (動画)`
          : `${sync.audio_format.toUpperCase()} / ${sync.audio_quality === "best" ? "Best" : sync.audio_quality + "kbps"}`}</div>
      </div>
      <div class="yt-sync-actions">
        <button class="btn btn-primary yt-sync-now-btn" data-id="${sync.id}" title="今すぐ同期">同期</button>
        <button class="btn btn-ghost yt-sync-toggle-btn" data-id="${sync.id}" data-enabled="${sync.enabled}">
          ${sync.enabled ? "一時停止" : "再開"}
        </button>
        <button class="btn btn-danger yt-sync-delete-btn" data-id="${sync.id}">削除</button>
      </div>
    </div>
    <div class="yt-sync-error-section">${errorBanner}</div>
    <div class="yt-list-feedback yt-sync-action-status" role="status" aria-live="polite"></div>
    <div class="yt-sync-tracks" id="yt-tracks-${sync.id}" style="display:none"></div>
    <button class="yt-tracks-toggle btn btn-ghost" data-id="${sync.id}">トラック一覧を表示 ▾</button>
  `;
}

function prepareSyncDetails(card, sync) {
  const actions = card.querySelector(".yt-sync-actions");
  const state = document.createElement("span");
  state.className = "yt-sync-state";
  card.querySelector(".yt-sync-title").append(state);
  const open = document.createElement("button");
  open.className = "btn btn-ghost yt-sync-detail-btn";
  open.textContent = "詳細 →";
  open.setAttribute("aria-expanded", "false");
  open.setAttribute("aria-controls", `sync-details-${sync.id}`);
  const drawer = document.createElement("section");
  drawer.className = "sync-detail-panel";
  drawer.id = `sync-details-${sync.id}`;
  drawer.hidden = true;
  drawer.setAttribute("aria-label", "プレイリストの詳細");
  const heading = document.createElement("div");
  heading.className = "sync-detail-heading";
  heading.innerHTML = '<div><span class="eyebrow">PLAYLIST DETAILS</span><h2 class="sync-detail-title"></h2></div><button type="button" class="btn btn-ghost close-sync-detail" aria-label="詳細を閉じる">✕</button>';
  drawer.append(heading);
  const controls = document.createElement("div");
  controls.className = "sync-detail-actions";
  controls.append(card.querySelector(".yt-sync-now-btn"), card.querySelector(".yt-sync-delete-btn"));
  const detailStatus = document.createElement("div");
  detailStatus.className = "yt-list-feedback yt-sync-detail-status";
  detailStatus.setAttribute("role", "status");
  detailStatus.setAttribute("aria-live", "polite");
  drawer.append(card.querySelector(".yt-sync-format"), controls, detailStatus, card.querySelector(".yt-sync-error-section"), card.querySelector(".yt-tracks-toggle"), card.querySelector(".yt-sync-tracks"));
  card.append(drawer);
  actions.append(open);
  const close = () => {
    drawer.hidden = true;
    card.classList.remove("details-open");
    open.setAttribute("aria-expanded", "false");
    open.focus({preventScroll: true});
  };
  const show = () => {
    if (!drawer.hidden) return;
    document.querySelectorAll(".sync-detail-panel").forEach(panel => {
      panel.hidden = true;
      panel.closest(".yt-sync-card").classList.remove("details-open");
      panel.closest(".yt-sync-card").querySelector(".yt-sync-detail-btn").setAttribute("aria-expanded", "false");
    });
    drawer.hidden = false;
    card.classList.add("details-open");
    open.setAttribute("aria-expanded", "true");
    heading.querySelector("button").focus({preventScroll: true});
  };
  open.addEventListener("click", () => drawer.hidden ? show() : close());
  card.addEventListener("click", event => {
    // Controls and the detail panel keep their own actions.
    if (event.target.closest("button, a, input, select, textarea, summary, .sync-detail-panel")) return;
    const selection = window.getSelection();
    if (selection?.toString() && (card.contains(selection.anchorNode) || card.contains(selection.focusNode))) return;
    show();
  });
  heading.querySelector("button").addEventListener("click", close);
  card.addEventListener("keydown", event => {
    if (event.key === "Escape" && !drawer.hidden) { close(); event.stopPropagation(); }
  });
}

function bindSyncCardEvents(card, sync) {
  function actionStatus(message, error = false) {
    for (const element of card.querySelectorAll(".yt-sync-action-status, .yt-sync-detail-status")) {
      element.textContent = message;
      element.classList.toggle("error-msg", error);
    }
  }
  card.querySelector(".yt-sync-error-section").addEventListener("click", (event) => {
    const errorDetailBtn = event.target.closest(".yt-sync-error-detail-btn");
    if (errorDetailBtn) {
      const detail = document.getElementById(`yt-sync-error-${sync.id}`);
      const expanded = detail.style.display !== "none";
      detail.style.display = expanded ? "none" : "";
      errorDetailBtn.textContent = expanded ? "詳細を見る ▾" : "詳細を隠す ▴";
    }
  });

  card.querySelector(".yt-sync-now-btn").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.dataset.busy = "true";
    btn.textContent = "同期中…";
    actionStatus("同期を依頼中…");
    try {
      await api.youtubeSyncNow(sync.id);
      btn.textContent = "キュー登録済み";
      actionStatus("同期をキューに追加しました");
      setTimeout(() => {
        btn.disabled = false;
        delete btn.dataset.busy;
        btn.textContent = "同期";
        renderSyncList();
      }, 3000);
    } catch (err) {
      btn.disabled = false;
      delete btn.dataset.busy;
      btn.textContent = "同期";
      actionStatus("同期に失敗しました: " + err.message, true);
    }
  });

  card.querySelector(".yt-sync-toggle-btn").addEventListener("click", async (e) => {
    if (card.dataset.mutating) return;
    const btn = e.currentTarget;
    const restoreFocus = document.activeElement === btn;
    const enabled = btn.dataset.enabled === "true";
    btn.disabled = true;
    btn.dataset.busy = "true";
    btn.textContent = "保存中…";
    setCardMutation(card, true);
    try {
      invalidateSyncRequests();
      const updated = await api.youtubeUpdateSync(sync.id, { enabled: !enabled });
      invalidateSyncRequests();
      applySync(updated);
      actionStatus(updated.enabled ? "同期を再開しました" : "同期を一時停止しました");
    } catch (err) {
      actionStatus("更新に失敗しました: " + err.message, true);
    } finally {
      btn.disabled = false;
      delete btn.dataset.busy;
      setCardMutation(card, false);
      updateSyncCard(card, syncRecords.get(String(sync.id)) || sync);
      if (restoreFocus && document.activeElement === document.body && btn.isConnected) btn.focus({preventScroll: true});
    }
  });

  card.querySelector(".yt-sync-delete-btn").addEventListener("click", async (e) => {
    if (card.dataset.mutating) return;
    const current = syncRecords.get(String(sync.id)) || sync;
    const deleteFiles = confirm(`「${current.playlist_name}」の同期を削除しますか？\n\n[OK] ダウンロード済みファイルも削除\n[キャンセル] 設定のみ削除`);
    const cancelAll = !deleteFiles && !confirm("設定のみ削除しますか？");
    if (cancelAll) return;
    setCardMutation(card, true);
    try {
      invalidateSyncRequests();
      await api.youtubeDeleteSync(sync.id, deleteFiles);
      invalidateSyncRequests();
      syncRecords.delete(String(sync.id));
      syncCards.delete(String(sync.id));
      reconcileRows(document.getElementById("yt-sync-list"), [...syncCards.values()], ".yt-sync-card", "同期中のプレイリストはありません");
      updateAccountSyncBadges();
    } catch (err) {
      actionStatus("削除に失敗しました: " + err.message, true);
    } finally {
      setCardMutation(card, false);
    }
  });

  card.querySelector(".yt-tracks-toggle").addEventListener("click", (e) => {
    const btn = e.currentTarget;
    const tracksDiv = document.getElementById(`yt-tracks-${sync.id}`);
    if (tracksDiv.style.display === "none") {
      tracksDiv.style.display = "";
      btn.textContent = "トラック一覧を非表示 ▴";
      renderSyncTracks(sync.id, tracksDiv);
    } else {
      tracksDiv.style.display = "none";
      btn.textContent = "トラック一覧を表示 ▾";
    }
  });
}

async function renderSyncTracks(syncId, container) {
  const request = (trackRequests.get(container) || 0) + 1;
  trackRequests.set(container, request);
  if (!container.querySelector(".yt-track-item")) container.innerHTML = '<div class="empty-state">読込中…</div>';
  try {
    const tracks = await api.youtubeListSyncTracks(syncId);
    if (request !== trackRequests.get(container) || !container.isConnected) return;
    if (!Array.isArray(tracks)) throw new Error("トラックを取得できませんでした");
    if (!tracks.length) {
      container.innerHTML = '<div class="empty-state">トラックなし</div>';
      return;
    }
    const fragment = document.createDocumentFragment();
    for (const t of tracks) {
      const item = document.createElement("div");
      item.className = "yt-track-item";
      const errorSection = t.status === "failed" && t.error_message ? `
        <div class="yt-track-error-row">
          <button class="btn btn-ghost yt-track-error-btn" data-track-id="${t.id}">詳細を見る ▾</button>
          <pre class="yt-track-error-text" id="yt-track-err-${t.id}" style="display:none">${escHtml(t.error_message)}</pre>
        </div>
      ` : "";
      item.innerHTML = `
        ${t.thumbnail_url
          ? `<img class="track-thumb" src="${escHtml(t.thumbnail_url)}" alt="" loading="lazy">`
          : '<div class="track-thumb-placeholder">♪</div>'}
        <div class="track-info">
          <div class="track-title">
            <span class="yt-id-badge" title="トラックID（DB障害メッセージの track_id= と一致）">#${t.id}</span>
            ${escHtml(t.title)}
          </div>
          <div class="track-artist">${escHtml(t.artist || "")}</div>
          ${errorSection}
        </div>
        <div class="yt-track-right">
          <span class="status-badge status-${t.status}">${statusLabel(t.status)}</span>
          ${t.duration_secs ? `<span class="track-duration">${fmtDuration(t.duration_secs)}</span>` : ""}
        </div>
      `;
      if (t.stream_url) {
        item.style.cursor = "pointer";
        item.addEventListener("click", () => playTrack(t));
      }
      const errBtn = item.querySelector(".yt-track-error-btn");
      if (errBtn) {
        errBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          const errPre = document.getElementById(`yt-track-err-${t.id}`);
          const expanded = errPre.style.display !== "none";
          errPre.style.display = expanded ? "none" : "";
          errBtn.textContent = expanded ? "詳細を見る ▾" : "詳細を隠す ▴";
        });
      }
      fragment.appendChild(item);
    }
    const scrollTop = container.scrollTop;
    container.replaceChildren(fragment);
    container.scrollTop = scrollTop;
  } catch (e) {
    if (request !== trackRequests.get(container) || !container.isConnected) return;
    if (!container.querySelector(".yt-track-item")) container.innerHTML = `<div class="error-msg">${escHtml(e.message)}</div>`;
    else {
      let notice = container.querySelector(".yt-track-refresh-error");
      if (!notice) { notice = document.createElement("div"); notice.className = "error-msg yt-track-refresh-error"; container.prepend(notice); }
      notice.textContent = `更新に失敗しました: ${e.message}`;
    }
  }
}

// ── Player integration ────────────────────────────────────────────────────────

function playTrack(track) {
  // Dispatch a custom event that player.js can listen to
  window.dispatchEvent(new CustomEvent("play-playlist-track", { detail: track }));
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatOptionsHTML() {
  return `
    <option value="mp3">MP3</option>
    <option value="m4a">M4A</option>
    <option value="flac">FLAC</option>
    <option value="aac">AAC</option>
    <option value="ogg">OGG</option>
    <option value="mp4">MP4 (動画)</option>
    <option value="webm">WEBM (動画)</option>
  `;
}

function statusLabel(status) {
  const map = { pending: "待機中", downloading: "DL中", complete: "完了", failed: "失敗", removed: "削除済" };
  return map[status] || status;
}

function fmtDuration(secs) {
  const m = Math.floor(secs / 60);
  const s = String(secs % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function escHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
