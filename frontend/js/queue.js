import { api, subscribeQueueEvents } from "./api.js";

let jobs = [];
let es = null;

export function initQueue() {
  renderUrlList();
  renderJobList();
  startSSE();
  renderUrlSyncInterval();
  document.getElementById("add-url-form").addEventListener("submit", handleAddUrl);
}

async function handleAddUrl(e) {
  e.preventDefault();
  const form = e.target;
  const url = form.url.value.trim();
  const audio_format = form.audio_format.value;
  const audio_quality = form.audio_quality.value;
  const errEl = document.getElementById("url-error");
  errEl.textContent = "";

  try {
    await api.addUrl({ url, audio_format, audio_quality, sync_enabled: true });
    form.url.value = "";
    renderUrlList();
    renderJobList();
  } catch (err) {
    errEl.textContent = err.message;
  }
}

async function renderUrlList() {
  const container = document.getElementById("url-list");
  try {
    const urls = await api.listUrls();
    container.innerHTML = urls.length ? "" : '<div class="empty-state">No URLs registered</div>';
    for (const src of urls) {
      const item = document.createElement("div");
      item.className = "url-item";
      item.innerHTML = `
        <div class="url-item-info">
          <div class="url-item-title">${escHtml(src.title || src.url)}</div>
          <div class="url-item-meta">${src.url_type} · ${src.audio_format}/${src.audio_quality}kbps · ${src.sync_enabled ? "auto-sync on" : "auto-sync off"}</div>
        </div>
        <div class="url-item-actions">
          <button class="btn btn-ghost delete-url" data-id="${src.id}">✕</button>
        </div>
      `;
      container.appendChild(item);
    }
    container.querySelectorAll(".delete-url").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await api.deleteUrl(Number(btn.dataset.id), false);
        renderUrlList();
      });
    });
  } catch {}
}

async function renderJobList() {
  const container = document.getElementById("job-list");
  try {
    jobs = await api.listQueue("pending,downloading,failed");
    renderJobs(container, jobs);
  } catch {}
}

function renderJobs(container, jobList) {
  container.innerHTML = jobList.length ? "" : '<div class="empty-state">No active downloads</div>';
  for (const job of jobList) {
    const item = document.createElement("div");
    item.className = "job-item";
    item.dataset.jobId = job.id;
    item.innerHTML = jobHTML(job);
    container.appendChild(item);
  }
  bindJobActions(container);
}

function jobHTML(job) {
  const pct = job.progress_pct || 0;
  return `
    <div class="job-header">
      <span class="job-title">${escHtml(job.title || job.youtube_id)}</span>
      <span class="status-badge status-${job.status}">${job.status}</span>
      ${job.status === "failed" ? `<button class="btn btn-ghost retry-job" data-id="${job.id}">↺</button>` : ""}
      <button class="btn btn-ghost cancel-job" data-id="${job.id}">✕</button>
    </div>
    <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
  `;
}

function bindJobActions(container) {
  container.querySelectorAll(".cancel-job").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await api.cancelJob(Number(btn.dataset.id)).catch(() => {});
      renderJobList();
    });
  });
  container.querySelectorAll(".retry-job").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await api.retryJob(Number(btn.dataset.id)).catch(() => {});
      renderJobList();
    });
  });
}

function startSSE() {
  if (es) es.close();
  es = subscribeQueueEvents((events) => {
    const container = document.getElementById("job-list");
    for (const ev of events) {
      const el = container.querySelector(`[data-job-id="${ev.job_id}"]`);
      if (el) {
        el.querySelector(".status-badge").className = `status-badge status-${ev.status}`;
        el.querySelector(".status-badge").textContent = ev.status;
        el.querySelector(".progress-fill").style.width = `${ev.progress_pct}%`;
      }
    }
    // Refresh list if any job completed/failed
    if (events.some((e) => e.status === "complete" || e.status === "failed")) {
      setTimeout(() => renderJobList(), 500);
    }
  });
}

async function renderUrlSyncInterval() {
  const select = document.getElementById("url-sync-interval");
  if (!select) return;
  try {
    const s = await api.getSettings();
    select.value = String(s.url_sync_interval_minutes);
  } catch {}
  select.addEventListener("change", async () => {
    try {
      await api.updateSettings({ url_sync_interval_minutes: Number(select.value) });
    } catch (e) {
      alert("設定の保存に失敗しました: " + e.message);
    }
  });
}

function escHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
