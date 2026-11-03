import { api, subscribeQueueEvents } from "./api.js";
import { bindMediaDefaults, loadDownloadPreferences } from "./download-preferences.js";

let jobs = [];
let es = null;
let jobListRequest = 0;

export function initQueue() {
  const form = document.getElementById("add-url-form");
  bindMediaDefaults(form.elements.namedItem("audio_format"), form.elements.namedItem("audio_quality"), document.getElementById("download-media-summary"), document.getElementById("url-error"));
  renderUrlList();
  renderJobList();
  startSSE();
  document.addEventListener("url-sources-updated", () => {renderUrlList();renderJobList();});
  document.getElementById("add-url-form").addEventListener("submit", handleAddUrl);
}

async function handleAddUrl(e) {
  e.preventDefault();
  const form = e.target;
  const url = form.elements.namedItem("url").value.trim();
  const errEl = document.getElementById("url-error");
  errEl.textContent = "";

  try {
    await loadDownloadPreferences();
    const audio_format = form.elements.namedItem("audio_format").value;
    const audio_quality = form.elements.namedItem("audio_quality").value;
    await api.addUrl({ url, audio_format, audio_quality, sync_enabled: true });
    form.elements.namedItem("url").value = "";
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
    container.innerHTML = urls.length ? "" : '<div class="empty-state">登録済みのURLはありません</div>';
    for (const src of urls) {
      const item = document.createElement("div");
      item.className = "url-item";
      item.innerHTML = `
        <div class="url-item-info">
          <div class="url-item-title">${escHtml(src.title || src.url)}</div>
          <div class="url-item-meta">${src.url_type} · ${src.audio_format}/${src.audio_quality === "best" ? "best" : src.audio_quality + "kbps"} · ${src.sync_enabled ? "auto-sync on" : "auto-sync off"}</div>
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
  const request = ++jobListRequest;
  try {
    const result = await api.listQueue("pending,downloading,failed");
    if (request !== jobListRequest) return;
    jobs = result;
    renderJobs(container, jobs);
  } catch {}
}

function renderJobs(container, jobList) {
  container.innerHTML = jobList.length ? "" : '<div class="empty-state">処理中のダウンロードはありません</div>';
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
  let refreshing = false;
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
    // The server sends a snapshot of active jobs, excluding finished jobs.
    const activeIds = new Set(events.map(event => event.job_id));
    const changed = events.some(event => !jobs.some(job => job.id === event.job_id))
      || jobs.some(job => ["pending", "downloading"].includes(job.status) && !activeIds.has(job.id))
      || events.some(event => ["complete", "failed"].includes(event.status));
    if (changed && !refreshing) {
      refreshing = true;
      renderJobList().finally(() => { refreshing = false; });
    }
  });
}

function escHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
