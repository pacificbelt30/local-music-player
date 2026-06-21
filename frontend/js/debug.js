import { api } from "/js/api.js";

const REFRESH_INTERVAL = 15_000;
let _timer = null;
let _open = false;
let _lastData = null;
const _openDetails = new Set();

function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fmtDuration(secs) {
  if (secs == null) return "—";
  const abs = Math.abs(secs);
  const h = Math.floor(abs / 3600);
  const m = Math.floor((abs % 3600) / 60);
  const s = Math.floor(abs % 60);
  const sign = secs < 0 ? "-" : "";
  if (h > 0) return `${sign}${h}h ${m}m`;
  if (m > 0) return `${sign}${m}m ${s}s`;
  return `${sign}${s}s`;
}

function fmtUptime(secs) {
  if (secs == null) return "—";
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  const m = Math.floor((secs % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function fmtBytes(bytes) {
  if (bytes == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function statusDot(ok, warn) {
  if (warn) return `<span class="dbg-dot warn"></span>`;
  return ok ? `<span class="dbg-dot ok"></span>` : `<span class="dbg-dot err"></span>`;
}

function detailToggle(key) {
  const open = _openDetails.has(key);
  return `<button class="dbg-detail-btn" data-detail-key="${key}">${open ? "生ログを隠す" : "生ログを表示"}</button>`;
}

function detailPre(key, data) {
  if (!_openDetails.has(key)) return "";
  return `<pre class="dbg-detail-pre">${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
}

function renderWorkers(workers, workerCount) {
  const anyWorker = workerCount > 0;
  let html = `
    <div class="dbg-section-header">
      ${statusDot(anyWorker)}
      <span class="dbg-section-title">Celery ワーカー</span>
      <span class="dbg-badge">${workerCount} online</span>
      ${detailToggle("workers")}
    </div>`;

  if (workers.length === 0) {
    html += `<div class="dbg-empty">ワーカーが見つかりません</div>`;
  } else {
    html += `<div class="dbg-table">`;
    for (const w of workers) {
      const busy = w.active_tasks > 0;
      const concurrency = w.concurrency != null ? w.concurrency : "?";
      const shortName = w.name.replace(/^celery@/, "");
      html += `
        <div class="dbg-row">
          <div class="dbg-cell name">
            ${statusDot(true, busy)}
            <span class="dbg-worker-name" title="${escapeHtml(w.name)}">${escapeHtml(shortName)}</span>
          </div>
          <div class="dbg-cell">
            <span class="dbg-label">実行中</span>
            <span class="dbg-val ${busy ? "highlight" : ""}">${w.active_tasks} / ${concurrency}</span>
          </div>
          <div class="dbg-cell">
            <span class="dbg-label">予約/スケジュール</span>
            <span class="dbg-val muted">${w.reserved_tasks} / ${w.scheduled_tasks}</span>
          </div>
          ${w.active_task_names.length ? `
          <div class="dbg-cell tasks">
            ${w.active_task_names.map(t => `<span class="dbg-tag">${escapeHtml(t.split(".").pop())}</span>`).join("")}
          </div>` : ""}
        </div>`;
    }
    html += `</div>`;
  }
  html += detailPre("workers", workers);
  return html;
}

function renderQueue(q) {
  const hasStuck = q.stuck > 0;
  let html = `
    <div class="dbg-section-header">
      ${statusDot(!hasStuck, false)}${hasStuck ? statusDot(false, false) : ""}
      <span class="dbg-section-title">ダウンロードキュー</span>
      <span class="dbg-badge">計 ${q.total}</span>
      ${detailToggle("queue")}
    </div>
    <div class="dbg-stat-grid">
      <div class="dbg-stat">
        <div class="dbg-stat-val">${q.pending}</div>
        <div class="dbg-stat-label">待機中</div>
      </div>
      <div class="dbg-stat">
        <div class="dbg-stat-val highlight">${q.downloading}</div>
        <div class="dbg-stat-label">ダウンロード中</div>
      </div>
      <div class="dbg-stat">
        <div class="dbg-stat-val ok">${q.complete}</div>
        <div class="dbg-stat-label">完了</div>
      </div>
      <div class="dbg-stat">
        <div class="dbg-stat-val err">${q.failed}</div>
        <div class="dbg-stat-label">失敗</div>
      </div>
      <div class="dbg-stat">
        <div class="dbg-stat-val muted">${q.skipped}</div>
        <div class="dbg-stat-label">スキップ</div>
      </div>
      <div class="dbg-stat">
        <div class="dbg-stat-val ${hasStuck ? "warn" : "muted"}">${q.stuck}</div>
        <div class="dbg-stat-label">スタック</div>
      </div>
    </div>`;
  html += detailPre("queue", q.recent_jobs);
  return html;
}

function renderOAuth(oauth) {
  const expiryColor = oauth.is_expired ? "err" : oauth.needs_refresh ? "warn" : "ok";
  const expiryLabel = oauth.is_expired ? "期限切れ" : oauth.needs_refresh ? "もうすぐ期限切れ" : "有効";
  const expiryDot = oauth.is_expired ? statusDot(false) : oauth.needs_refresh ? statusDot(true, true) : statusDot(true);

  let html = `
    <div class="dbg-section-header">
      ${oauth.authenticated ? expiryDot : statusDot(false)}
      <span class="dbg-section-title">YouTube OAuth</span>
      ${oauth.authenticated ? `<span class="dbg-badge ${expiryColor}">${expiryLabel}</span>` : `<span class="dbg-badge err">未認証</span>`}
      ${detailToggle("oauth")}
    </div>`;

  if (!oauth.authenticated) {
    html += `<div class="dbg-empty">トークンが登録されていません</div>`;
    html += detailPre("oauth", oauth);
    return html;
  }

  const expiry = oauth.token_expiry ? new Date(oauth.token_expiry + "Z") : null;
  const expiryStr = expiry ? expiry.toLocaleString("ja-JP") : "—";

  html += `
    <div class="dbg-table">
      <div class="dbg-row">
        <div class="dbg-cell"><span class="dbg-label">有効期限</span></div>
        <div class="dbg-cell"><span class="dbg-val">${expiryStr}</span></div>
      </div>
      <div class="dbg-row">
        <div class="dbg-cell"><span class="dbg-label">残り時間</span></div>
        <div class="dbg-cell"><span class="dbg-val ${expiryColor}">${fmtDuration(oauth.expires_in_seconds)}</span></div>
      </div>
      <div class="dbg-row">
        <div class="dbg-cell"><span class="dbg-label">トークン</span></div>
        <div class="dbg-cell"><span class="dbg-val muted">${escapeHtml(oauth.access_token_preview)} ${oauth.refresh_token_set ? "(refresh あり)" : "(refresh なし)"}</span></div>
      </div>
      <div class="dbg-row">
        <div class="dbg-cell"><span class="dbg-label">スコープ</span></div>
        <div class="dbg-cell"><span class="dbg-val scope-val">${escapeHtml(oauth.scope) || "—"}</span></div>
      </div>
    </div>`;
  html += detailPre("oauth", oauth);
  return html;
}

function renderRedis(redis) {
  let html = `
    <div class="dbg-section-header">
      ${statusDot(redis.connected)}
      <span class="dbg-section-title">Redis</span>
      <span class="dbg-badge ${redis.connected ? "ok" : "err"}">${redis.connected ? "接続中" : "切断"}</span>
      ${redis.connected ? detailToggle("redis") : ""}
    </div>`;

  if (!redis.connected) {
    html += `<div class="dbg-empty">Redis に接続できません</div>`;
    return html;
  }

  html += `
    <div class="dbg-table">
      <div class="dbg-row">
        <div class="dbg-cell"><span class="dbg-label">メモリ使用量</span></div>
        <div class="dbg-cell"><span class="dbg-val">${escapeHtml(redis.used_memory_human) || "—"}</span></div>
      </div>
      <div class="dbg-row">
        <div class="dbg-cell"><span class="dbg-label">クライアント数</span></div>
        <div class="dbg-cell"><span class="dbg-val">${redis.connected_clients ?? "—"}</span></div>
      </div>
      <div class="dbg-row">
        <div class="dbg-cell"><span class="dbg-label">稼働時間</span></div>
        <div class="dbg-cell"><span class="dbg-val">${fmtUptime(redis.uptime_in_seconds)}</span></div>
      </div>
      <div class="dbg-row">
        <div class="dbg-cell"><span class="dbg-label">総コマンド数</span></div>
        <div class="dbg-cell"><span class="dbg-val">${redis.total_commands_processed?.toLocaleString() ?? "—"}</span></div>
      </div>
    </div>`;
  html += detailPre("redis", redis.raw);
  return html;
}

function renderDB(db) {
  let html = `
    <div class="dbg-section-header">
      ${statusDot(true)}
      <span class="dbg-section-title">データベース</span>
    </div>
    <div class="dbg-stat-grid">
      <div class="dbg-stat">
        <div class="dbg-stat-val">${db.tracks}</div>
        <div class="dbg-stat-label">トラック</div>
      </div>
      <div class="dbg-stat">
        <div class="dbg-stat-val">${db.download_jobs}</div>
        <div class="dbg-stat-label">ダウンロードJOB</div>
      </div>
      <div class="dbg-stat">
        <div class="dbg-stat-val">${db.url_sources}</div>
        <div class="dbg-stat-label">URL登録数</div>
      </div>
      <div class="dbg-stat">
        <div class="dbg-stat-val">${db.youtube_syncs}</div>
        <div class="dbg-stat-label">YT同期設定</div>
      </div>
      <div class="dbg-stat">
        <div class="dbg-stat-val">${db.playlist_sync_tracks}</div>
        <div class="dbg-stat-label">同期トラック</div>
      </div>
    </div>`;
  return html;
}

function renderBeat(schedule) {
  let html = `
    <div class="dbg-section-header">
      ${statusDot(true)}
      <span class="dbg-section-title">Celery Beat スケジュール</span>
      ${detailToggle("beat")}
    </div>`;

  if (!schedule.length) {
    html += `<div class="dbg-empty">スケジュールなし</div>`;
    html += detailPre("beat", schedule);
    return html;
  }

  html += `<div class="dbg-table">`;
  for (const t of schedule) {
    const shortTask = t.name.split(".").pop();
    html += `
      <div class="dbg-row">
        <div class="dbg-cell"><span class="dbg-tag">${escapeHtml(shortTask)}</span></div>
        <div class="dbg-cell"><span class="dbg-val muted">${escapeHtml(t.schedule)}</span></div>
      </div>`;
  }
  html += `</div>`;
  html += detailPre("beat", schedule);
  return html;
}

function renderDisk(diskUsage) {
  let html = `
    <div class="dbg-section-header">
      ${statusDot(true)}
      <span class="dbg-section-title">ディスク使用量</span>
    </div>`;

  if (!diskUsage.length) {
    html += `<div class="dbg-empty">取得できません</div>`;
    return html;
  }

  html += `<div class="dbg-table">`;
  for (const d of diskUsage) {
    const pct = d.total_bytes > 0 ? Math.round((d.used_bytes / d.total_bytes) * 100) : 0;
    const low = d.free_bytes < 1024 ** 3; // < 1GB free
    html += `
      <div class="dbg-row">
        <div class="dbg-cell name">
          ${statusDot(!low, low)}
          <span class="dbg-worker-name" title="${escapeHtml(d.path)}">${escapeHtml(d.label)}</span>
        </div>
        <div class="dbg-cell">
          <span class="dbg-label">使用率</span>
          <span class="dbg-val ${low ? "warn" : ""}">${pct}%</span>
        </div>
        <div class="dbg-cell">
          <span class="dbg-label">空き</span>
          <span class="dbg-val muted">${fmtBytes(d.free_bytes)} / ${fmtBytes(d.total_bytes)}</span>
        </div>
      </div>`;
  }
  html += `</div>`;
  return html;
}

function renderSyncErrors(syncErrors) {
  let html = `
    <div class="dbg-section-header">
      ${statusDot(syncErrors.length === 0)}
      <span class="dbg-section-title">YouTube同期エラー</span>
      <span class="dbg-badge ${syncErrors.length ? "err" : "ok"}">${syncErrors.length}</span>
    </div>`;

  if (!syncErrors.length) {
    html += `<div class="dbg-empty">エラーはありません</div>`;
    return html;
  }

  html += `<div class="dbg-table">`;
  for (const s of syncErrors) {
    const lastSynced = s.last_synced ? new Date(s.last_synced + "Z").toLocaleString("ja-JP") : "—";
    html += `
      <div class="dbg-row">
        <div class="dbg-cell name">
          ${statusDot(false)}
          <span class="dbg-worker-name" title="${escapeHtml(s.playlist_name)}">${escapeHtml(s.playlist_name)}</span>
        </div>
        <div class="dbg-cell">
          <span class="dbg-label">最終同期</span>
          <span class="dbg-val muted">${lastSynced}</span>
        </div>
        <div class="dbg-cell tasks">
          <span class="dbg-val err" style="font-size:0.72rem;word-break:break-all;">${escapeHtml(s.last_error)}</span>
        </div>
      </div>`;
  }
  html += `</div>`;
  return html;
}

function renderAppInfo(appInfo) {
  const startedAt = new Date(appInfo.started_at + "Z").toLocaleString("ja-JP");
  return `
    <div class="dbg-section-header">
      ${statusDot(true)}
      <span class="dbg-section-title">アプリ情報</span>
    </div>
    <div class="dbg-table">
      <div class="dbg-row">
        <div class="dbg-cell"><span class="dbg-label">バージョン</span></div>
        <div class="dbg-cell"><span class="dbg-val">${escapeHtml(appInfo.version)}</span></div>
      </div>
      <div class="dbg-row">
        <div class="dbg-cell"><span class="dbg-label">起動時刻</span></div>
        <div class="dbg-cell"><span class="dbg-val">${startedAt}</span></div>
      </div>
      <div class="dbg-row">
        <div class="dbg-cell"><span class="dbg-label">稼働時間</span></div>
        <div class="dbg-cell"><span class="dbg-val">${fmtUptime(appInfo.uptime_seconds)}</span></div>
      </div>
    </div>`;
}

function render(data) {
  _lastData = data;
  const serverTime = new Date(data.server_time).toLocaleString("ja-JP");
  const el = document.getElementById("debug-modal-body");
  if (!el) return;

  el.innerHTML = `
    <div class="dbg-timestamp">最終更新: ${serverTime} <span class="dbg-refresh-info">（15秒ごとに自動更新）</span></div>
    <div class="dbg-grid">
      <div class="dbg-card">${renderWorkers(data.workers, data.worker_count)}</div>
      <div class="dbg-card">${renderQueue(data.queue)}</div>
      <div class="dbg-card">${renderOAuth(data.oauth)}</div>
      <div class="dbg-card">${renderRedis(data.redis)}</div>
      <div class="dbg-card">${renderDB(data.db)}</div>
      <div class="dbg-card">${renderBeat(data.beat_schedule)}</div>
      <div class="dbg-card">${renderDisk(data.disk_usage)}</div>
      <div class="dbg-card">${renderSyncErrors(data.sync_errors)}</div>
      <div class="dbg-card">${renderAppInfo(data.app_info)}</div>
    </div>`;
}

function renderError(msg) {
  const el = document.getElementById("debug-modal-body");
  if (el) el.innerHTML = `<div class="dbg-error">取得エラー: ${msg}</div>`;
}

async function refresh() {
  try {
    const data = await api.getDebug();
    render(data);
  } catch (e) {
    renderError(e.message || "不明なエラー");
  }
}

function startPolling() {
  refresh();
  _timer = setInterval(refresh, REFRESH_INTERVAL);
}

function stopPolling() {
  if (_timer) {
    clearInterval(_timer);
    _timer = null;
  }
}

export function initDebug() {
  const btn = document.getElementById("debug-badge");
  const modal = document.getElementById("debug-modal");
  if (!btn || !modal) return;

  const modalBody = document.getElementById("debug-modal-body");
  if (modalBody) {
    modalBody.addEventListener("click", (e) => {
      const toggleBtn = e.target.closest(".dbg-detail-btn");
      if (!toggleBtn) return;
      const key = toggleBtn.dataset.detailKey;
      if (_openDetails.has(key)) {
        _openDetails.delete(key);
      } else {
        _openDetails.add(key);
      }
      if (_lastData) render(_lastData);
    });
  }

  btn.addEventListener("click", () => {
    modal.classList.remove("hidden");
    _open = true;
    startPolling();
  });

  modal.querySelectorAll("[data-close-debug-modal]").forEach((el) => {
    el.addEventListener("click", () => {
      modal.classList.add("hidden");
      _open = false;
      stopPolling();
    });
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && _open) {
      modal.classList.add("hidden");
      _open = false;
      stopPolling();
    }
  });

  // Manual refresh button
  const refreshBtn = document.getElementById("debug-refresh-btn");
  if (refreshBtn) refreshBtn.addEventListener("click", refresh);
}
