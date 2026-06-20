import { api } from "/js/api.js";

const REFRESH_INTERVAL = 30_000;
let _timer = null;
let _open = false;

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

function statusDot(ok, warn) {
  if (warn) return `<span class="dbg-dot warn"></span>`;
  return ok ? `<span class="dbg-dot ok"></span>` : `<span class="dbg-dot err"></span>`;
}

function renderWorkers(workers, workerCount) {
  const anyWorker = workerCount > 0;
  let html = `
    <div class="dbg-section-header">
      ${statusDot(anyWorker)}
      <span class="dbg-section-title">Celery ワーカー</span>
      <span class="dbg-badge">${workerCount} online</span>
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
            <span class="dbg-worker-name" title="${w.name}">${shortName}</span>
          </div>
          <div class="dbg-cell">
            <span class="dbg-label">実行中</span>
            <span class="dbg-val ${busy ? "highlight" : ""}">${w.active_tasks} / ${concurrency}</span>
          </div>
          ${w.active_task_names.length ? `
          <div class="dbg-cell tasks">
            ${w.active_task_names.map(t => `<span class="dbg-tag">${t.split(".").pop()}</span>`).join("")}
          </div>` : ""}
        </div>`;
    }
    html += `</div>`;
  }
  return html;
}

function renderQueue(q) {
  const hasStuck = q.stuck > 0;
  let html = `
    <div class="dbg-section-header">
      ${statusDot(!hasStuck, false)}${hasStuck ? statusDot(false, false) : ""}
      <span class="dbg-section-title">ダウンロードキュー</span>
      <span class="dbg-badge">計 ${q.total}</span>
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
    </div>`;

  if (!oauth.authenticated) {
    html += `<div class="dbg-empty">トークンが登録されていません</div>`;
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
        <div class="dbg-cell"><span class="dbg-label">スコープ</span></div>
        <div class="dbg-cell"><span class="dbg-val scope-val">${oauth.scope || "—"}</span></div>
      </div>
    </div>`;
  return html;
}

function renderRedis(redis) {
  let html = `
    <div class="dbg-section-header">
      ${statusDot(redis.connected)}
      <span class="dbg-section-title">Redis</span>
      <span class="dbg-badge ${redis.connected ? "ok" : "err"}">${redis.connected ? "接続中" : "切断"}</span>
    </div>`;

  if (!redis.connected) {
    html += `<div class="dbg-empty">Redis に接続できません</div>`;
    return html;
  }

  html += `
    <div class="dbg-table">
      <div class="dbg-row">
        <div class="dbg-cell"><span class="dbg-label">メモリ使用量</span></div>
        <div class="dbg-cell"><span class="dbg-val">${redis.used_memory_human || "—"}</span></div>
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
    </div>`;

  if (!schedule.length) {
    html += `<div class="dbg-empty">スケジュールなし</div>`;
    return html;
  }

  html += `<div class="dbg-table">`;
  for (const t of schedule) {
    const shortTask = t.name.split(".").pop();
    html += `
      <div class="dbg-row">
        <div class="dbg-cell"><span class="dbg-tag">${shortTask}</span></div>
        <div class="dbg-cell"><span class="dbg-val muted">${t.schedule}</span></div>
      </div>`;
  }
  html += `</div>`;
  return html;
}

function render(data) {
  const serverTime = new Date(data.server_time).toLocaleString("ja-JP");
  const el = document.getElementById("debug-modal-body");
  if (!el) return;

  el.innerHTML = `
    <div class="dbg-timestamp">最終更新: ${serverTime} <span class="dbg-refresh-info">（30秒ごとに自動更新）</span></div>
    <div class="dbg-grid">
      <div class="dbg-card">${renderWorkers(data.workers, data.worker_count)}</div>
      <div class="dbg-card">${renderQueue(data.queue)}</div>
      <div class="dbg-card">${renderOAuth(data.oauth)}</div>
      <div class="dbg-card">${renderRedis(data.redis)}</div>
      <div class="dbg-card">${renderDB(data.db)}</div>
      <div class="dbg-card">${renderBeat(data.beat_schedule)}</div>
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
