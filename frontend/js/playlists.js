import { api } from "./api.js";

let syncPollers = {};

export function initPlaylists() {
  renderAuthSection();
  renderSyncList();

  // Handle youtube_auth=success redirect from OAuth callback
  if (new URLSearchParams(location.search).get("youtube_auth") === "success") {
    history.replaceState({}, "", "/");
    renderAuthSection();
    renderSyncList();
  }
}

// ── Auth Section ──────────────────────────────────────────────────────────────

async function renderAuthSection() {
  const container = document.getElementById("yt-auth-section");
  if (!container) return;

  try {
    const status = await api.youtubeAuthStatus();
    if (status.authenticated) {
      container.innerHTML = `
        <div class="yt-auth-connected">
          <span class="status-badge status-complete">YouTube接続済み</span>
          <button class="btn btn-ghost" id="yt-token-toggle-btn">トークンを更新</button>
          <button class="btn btn-ghost" id="yt-disconnect-btn">接続解除</button>
        </div>
        ${tokenFormHTML()}
      `;
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
    container.innerHTML = `<div class="error-msg">${escHtml(e.message)}</div>`;
  }
}

function tokenFormHTML() {
  return `
    <div id="yt-token-form" style="display:none;margin-top:12px">
      <p class="yt-auth-hint" style="margin-bottom:8px">
        トークンは
        <a href="https://developers.google.com/oauthplayground/" target="_blank" rel="noopener">Google OAuth 2.0 Playground</a>
        で取得できます。Scope に
        <code>https://www.googleapis.com/auth/youtube.readonly</code> を指定してください。
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
    renderAuthSection();
    document.getElementById("yt-account-playlists").innerHTML = "";
  } catch (e) {
    alert("解除に失敗しました: " + e.message);
  }
}

// ── Account Playlists Picker ──────────────────────────────────────────────────

async function renderAccountPlaylists() {
  const container = document.getElementById("yt-account-playlists");
  if (!container) return;
  container.innerHTML = '<div class="empty-state">プレイリスト読込中…</div>';

  try {
    const playlists = await api.youtubeListAccountPlaylists();
    const syncs = await api.youtubeListSyncs();
    const syncedIds = new Set(syncs.map((s) => s.playlist_id));

    if (!playlists.length) {
      container.innerHTML = '<div class="empty-state">プレイリストが見つかりません</div>';
      return;
    }

    container.innerHTML = "";
    for (const pl of playlists) {
      const already = syncedIds.has(pl.playlist_id);
      const item = document.createElement("div");
      item.className = "yt-pl-item";
      item.innerHTML = `
        ${pl.thumbnail_url ? `<img class="yt-pl-thumb" src="${escHtml(pl.thumbnail_url)}" alt="" loading="lazy">` : '<div class="track-thumb-placeholder">▶</div>'}
        <div class="yt-pl-info">
          <div class="yt-pl-title">${escHtml(pl.title)}</div>
          <div class="yt-pl-meta">${pl.item_count} 曲</div>
        </div>
        <button class="btn ${already ? "btn-ghost" : "btn-primary"} yt-add-sync-btn"
          data-id="${escHtml(pl.playlist_id)}" data-name="${escHtml(pl.title)}"
          ${already ? "disabled" : ""}>
          ${already ? "同期中" : "+ 同期追加"}
        </button>
      `;
      container.appendChild(item);
    }

    container.querySelectorAll(".yt-add-sync-btn:not([disabled])").forEach((btn) => {
      btn.addEventListener("click", () => showAddSyncDialog(btn));
    });
  } catch (e) {
    container.innerHTML = `<div class="error-msg">${escHtml(e.message)}</div>`;
  }
}

// ── Add Sync Dialog ───────────────────────────────────────────────────────────

function showAddSyncDialog(btn) {
  const existing = document.getElementById("yt-add-sync-dialog");
  if (existing) existing.remove();

  const dialog = document.createElement("div");
  dialog.id = "yt-add-sync-dialog";
  dialog.className = "yt-add-sync-dialog";
  dialog.innerHTML = `
    <div class="yt-add-sync-dialog-inner">
      <div class="yt-add-sync-dialog-title">同期設定: ${escHtml(btn.dataset.name)}</div>
      <div class="format-row" style="margin-bottom:8px">
        <select id="yt-sync-format">
          <option value="mp3">MP3</option>
          <option value="flac">FLAC</option>
          <option value="aac">AAC</option>
          <option value="ogg">OGG</option>
        </select>
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
    dialog.remove();
    btn.disabled = true;
    btn.textContent = "追加中…";
    try {
      await api.youtubeCreateSync({
        playlist_id: btn.dataset.id,
        playlist_name: btn.dataset.name,
        audio_format,
        audio_quality,
      });
      btn.textContent = "同期中";
      btn.className = "btn btn-ghost yt-add-sync-btn";
      renderSyncList();
    } catch (e) {
      btn.disabled = false;
      btn.textContent = "+ 同期追加";
      alert("追加に失敗しました: " + e.message);
    }
  });
}

// ── Sync List ─────────────────────────────────────────────────────────────────

async function renderSyncList() {
  const container = document.getElementById("yt-sync-list");
  if (!container) return;

  try {
    const syncs = await api.youtubeListSyncs();
    container.innerHTML = syncs.length ? "" : '<div class="empty-state">同期中のプレイリストはありません</div>';

    for (const sync of syncs) {
      const card = document.createElement("div");
      card.className = "yt-sync-card";
      card.dataset.syncId = sync.id;
      card.innerHTML = syncCardHTML(sync);
      container.appendChild(card);
      bindSyncCardEvents(card, sync);
    }
  } catch (e) {
    container.innerHTML = `<div class="error-msg">${escHtml(e.message)}</div>`;
  }
}

function syncCardHTML(sync) {
  const lastSynced = sync.last_synced
    ? new Date(sync.last_synced).toLocaleString("ja-JP")
    : "未同期";
  const progress = sync.track_count
    ? `${sync.downloaded_count}/${sync.track_count} 曲ダウンロード済み`
    : "トラックなし";

  return `
    <div class="yt-sync-header">
      <div class="yt-sync-info">
        <div class="yt-sync-title">${escHtml(sync.playlist_name)}</div>
        <div class="yt-sync-meta">${progress} · 最終同期: ${lastSynced}</div>
        <div class="yt-sync-meta">${sync.audio_format.toUpperCase()} / ${sync.audio_quality === "best" ? "Best" : sync.audio_quality + "kbps"}</div>
      </div>
      <div class="yt-sync-actions">
        <button class="btn btn-primary yt-sync-now-btn" data-id="${sync.id}" title="今すぐ同期">同期</button>
        <button class="btn btn-ghost yt-sync-toggle-btn" data-id="${sync.id}" data-enabled="${sync.enabled}">
          ${sync.enabled ? "一時停止" : "再開"}
        </button>
        <button class="btn btn-danger yt-sync-delete-btn" data-id="${sync.id}">削除</button>
      </div>
    </div>
    <div class="yt-sync-tracks" id="yt-tracks-${sync.id}" style="display:none"></div>
    <button class="yt-tracks-toggle btn btn-ghost" data-id="${sync.id}">トラック一覧を表示 ▾</button>
  `;
}

function bindSyncCardEvents(card, sync) {
  card.querySelector(".yt-sync-now-btn").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.textContent = "同期中…";
    try {
      await api.youtubeSyncNow(sync.id);
      btn.textContent = "キュー登録済み";
      setTimeout(() => {
        btn.disabled = false;
        btn.textContent = "同期";
        renderSyncList();
      }, 3000);
    } catch (err) {
      btn.disabled = false;
      btn.textContent = "同期";
      alert("同期に失敗しました: " + err.message);
    }
  });

  card.querySelector(".yt-sync-toggle-btn").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const enabled = btn.dataset.enabled === "true";
    try {
      await api.youtubeUpdateSync(sync.id, { enabled: !enabled });
      renderSyncList();
    } catch (err) {
      alert("更新に失敗しました: " + err.message);
    }
  });

  card.querySelector(".yt-sync-delete-btn").addEventListener("click", async (e) => {
    const deleteFiles = confirm(`「${sync.playlist_name}」の同期を削除しますか？\n\n[OK] ダウンロード済みファイルも削除\n[キャンセル] 設定のみ削除`);
    const cancelAll = !deleteFiles && !confirm("設定のみ削除しますか？");
    if (cancelAll) return;
    try {
      await api.youtubeDeleteSync(sync.id, deleteFiles);
      card.remove();
      if (!document.querySelectorAll(".yt-sync-card").length) {
        document.getElementById("yt-sync-list").innerHTML = '<div class="empty-state">同期中のプレイリストはありません</div>';
      }
    } catch (err) {
      alert("削除に失敗しました: " + err.message);
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
  container.innerHTML = '<div class="empty-state">読込中…</div>';
  try {
    const tracks = await api.youtubeListSyncTracks(syncId);
    if (!tracks.length) {
      container.innerHTML = '<div class="empty-state">トラックなし</div>';
      return;
    }
    container.innerHTML = "";
    for (const t of tracks) {
      const item = document.createElement("div");
      item.className = "yt-track-item";
      item.innerHTML = `
        ${t.thumbnail_url
          ? `<img class="track-thumb" src="${escHtml(t.thumbnail_url)}" alt="" loading="lazy">`
          : '<div class="track-thumb-placeholder">♪</div>'}
        <div class="track-info">
          <div class="track-title">${escHtml(t.title)}</div>
          <div class="track-artist">${escHtml(t.artist || "")}</div>
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
      container.appendChild(item);
    }
  } catch (e) {
    container.innerHTML = `<div class="error-msg">${escHtml(e.message)}</div>`;
  }
}

// ── Player integration ────────────────────────────────────────────────────────

function playTrack(track) {
  // Dispatch a custom event that player.js can listen to
  window.dispatchEvent(new CustomEvent("play-playlist-track", { detail: track }));
}

// ── Helpers ───────────────────────────────────────────────────────────────────

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
