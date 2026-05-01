import { api } from "./api.js";

export function initSyncthing() {
  const modal = document.getElementById("syncthing-modal");
  if (!modal) return;

  bindConfigForm();

  document.getElementById("syncthing-badge")?.addEventListener("click", openModal);
  modal.querySelectorAll("[data-close-modal]").forEach((el) => {
    el.addEventListener("click", closeModal);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.classList.contains("hidden")) closeModal();
  });

  document.getElementById("syncthing-refresh-btn")?.addEventListener("click", () => {
    refreshFolders();
    refreshDevices();
  });
}

function openModal() {
  const modal = document.getElementById("syncthing-modal");
  if (!modal) return;
  modal.classList.remove("hidden");
  refreshConfig();
  refreshFolders();
  refreshDevices();
}

function closeModal() {
  document.getElementById("syncthing-modal")?.classList.add("hidden");
}

function bindConfigForm() {
  const form = document.getElementById("syncthing-config-form");
  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = form.url.value.trim();
    const apiKey = form.api_key.value;
    const errEl = document.getElementById("syncthing-config-error");
    const okEl = document.getElementById("syncthing-config-ok");
    errEl.textContent = "";
    okEl.textContent = "";

    const payload = { url };
    if (apiKey) payload.api_key = apiKey;

    try {
      await api.syncthingUpdateConfig(payload);
      okEl.textContent = "保存しました";
      form.api_key.value = "";
      refreshConfig();
      refreshFolders();
      refreshDevices();
    } catch (err) {
      errEl.textContent = err.message;
    }
  });

  document.getElementById("syncthing-test-btn")?.addEventListener("click", async () => {
    const url = form.url.value.trim();
    const apiKey = form.api_key.value || null;
    const errEl = document.getElementById("syncthing-config-error");
    const okEl = document.getElementById("syncthing-config-ok");
    errEl.textContent = "";
    okEl.textContent = "";

    if (!apiKey) {
      const cfg = await api.syncthingGetConfig().catch(() => null);
      if (!cfg?.api_key_set) {
        errEl.textContent = "テストには API キーを入力してください";
        return;
      }
      // Use stored key via status endpoint instead
      try {
        const status = await api.syncthingStatus();
        if (status.available) okEl.textContent = `接続OK (myID: ${status.my_id?.slice(0, 7) || "?"})`;
        else errEl.textContent = `接続失敗: ${status.reason}`;
      } catch (e) {
        errEl.textContent = e.message;
      }
      return;
    }

    try {
      const r = await api.syncthingTestConfig({ url, api_key: apiKey });
      if (r.ok) okEl.textContent = `接続OK (myID: ${(r.my_id || "").slice(0, 7)})`;
      else errEl.textContent = `接続失敗: ${r.reason || "不明"}`;
    } catch (e) {
      errEl.textContent = e.message;
    }
  });
}

async function refreshConfig() {
  try {
    const cfg = await api.syncthingGetConfig();
    const form = document.getElementById("syncthing-config-form");
    if (form) {
      form.url.value = cfg.url || "";
      form.api_key.placeholder = cfg.api_key_set ? "（保存済 — 変更する場合のみ入力）" : "API キー";
    }
    const stateEl = document.getElementById("syncthing-config-state");
    if (stateEl) {
      stateEl.textContent = cfg.api_key_set ? "API キー: 設定済み" : "API キー: 未設定";
      stateEl.className = "syncthing-config-state " + (cfg.api_key_set ? "ok" : "warn");
    }
  } catch (e) {
    const errEl = document.getElementById("syncthing-config-error");
    if (errEl) errEl.textContent = e.message;
  }
}

async function refreshFolders() {
  const container = document.getElementById("syncthing-folder-list");
  if (!container) return;
  container.innerHTML = '<div class="empty-state">読込中…</div>';
  try {
    const folders = await api.syncthingListFolders();
    if (!folders.length) {
      container.innerHTML = '<div class="empty-state">共有フォルダがありません</div>';
      return;
    }
    container.innerHTML = "";
    for (const f of folders) {
      const pct = Math.round(f.completion_pct ?? 100);
      const syncing = (f.need_bytes ?? 0) > 0;
      const statusColor = f.paused ? "var(--text-muted)" : syncing ? "var(--warning)" : "var(--success)";
      const statusLabel = f.paused ? "paused" : syncing ? `同期中 ${pct}%` : `完了 ${pct}%`;
      const needInfo = syncing ? ` · 残り ${esc(f.need_bytes_fmt || "")}、${f.need_items || 0} ファイル` : "";
      const row = document.createElement("div");
      row.className = "syncthing-row";
      row.innerHTML = `
        <div class="syncthing-row-info">
          <div class="syncthing-row-title">${esc(f.label || f.id)}</div>
          <div class="syncthing-row-meta">${esc(f.path || "")} · ${esc(f.type || "")}</div>
          <div class="syncthing-row-meta" style="margin-top:4px">
            <span style="color:${statusColor};font-weight:600">${statusLabel}</span>
            ${needInfo}
            · 合計 ${esc(f.global_bytes_fmt || "?")}
          </div>
          ${syncing ? `<div style="margin-top:6px;height:3px;background:var(--surface3);border-radius:99px;overflow:hidden"><div style="height:100%;width:${pct}%;background:var(--warning);transition:width 0.3s"></div></div>` : ""}
        </div>
        <button class="btn btn-ghost rescan-folder" data-id="${esc(f.id)}" title="再スキャン">↻</button>
      `;
      container.appendChild(row);
    }
    container.querySelectorAll(".rescan-folder").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await api.syncthingRescanFolder(btn.dataset.id);
          btn.textContent = "✓";
          setTimeout(() => { btn.textContent = "↻"; btn.disabled = false; }, 1500);
        } catch (e) {
          alert("再スキャンに失敗しました: " + e.message);
          btn.disabled = false;
        }
      });
    });
  } catch (e) {
    container.innerHTML = `<div class="empty-state">取得失敗: ${esc(e.message)}</div>`;
  }
}

async function refreshDevices() {
  const container = document.getElementById("syncthing-device-list");
  if (!container) return;
  container.innerHTML = '<div class="empty-state">読込中…</div>';
  try {
    const devices = await api.syncthingListDevices();
    if (!devices.length) {
      container.innerHTML = '<div class="empty-state">デバイスがありません</div>';
      return;
    }
    container.innerHTML = "";
    for (const d of devices) {
      const connColor = d.paused ? "var(--text-muted)" : d.connected ? "var(--success)" : "var(--text-muted)";
      const connLabel = d.paused ? "paused" : d.connected ? "接続中" : "未接続";
      const addressLine = d.connected && d.address ? ` · ${esc(d.address)}` : "";
      const versionLine = d.connected && d.client_version ? ` · ${esc(d.client_version)}` : "";
      const lastSeenLine = !d.connected && d.last_seen ? ` · 最終接続: ${esc(d.last_seen.slice(0, 10))}` : "";
      const row = document.createElement("div");
      row.className = "syncthing-row";
      row.innerHTML = `
        <div class="syncthing-row-info">
          <div class="syncthing-row-title">${esc(d.name || d.device_id?.slice(0, 7) || "?")}</div>
          <div class="syncthing-row-meta">${esc((d.device_id || "").slice(0, 23))}…</div>
          <div class="syncthing-row-meta" style="margin-top:3px">
            <span style="color:${connColor};font-weight:600">${connLabel}</span>${addressLine}${versionLine}${lastSeenLine}
          </div>
        </div>
      `;
      container.appendChild(row);
    }
  } catch (e) {
    container.innerHTML = `<div class="empty-state">取得失敗: ${esc(e.message)}</div>`;
  }
}

function esc(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
