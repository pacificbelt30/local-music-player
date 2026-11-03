import { api, subscribeQueueEvents } from "./api.js";
import {
  bindMediaDefaults,
  loadDownloadPreferences,
} from "./download-preferences.js";

let jobs = [];
let es = null;
let jobListRequest = 0;
let fetchingJobs = false;
let urlListRequest = 0;
let pageAway = false;
const busyJobs = new Set();
const busyUrls = new Set();
const labels = {
  pending: "待機中",
  downloading: "取得中",
  failed: "失敗",
  complete: "完了",
  skipped: "保留",
};
const percent = (value) => Math.min(100, Math.max(0, Number(value) || 0));

function notice(id, message = "", retry) {
  const element = document.getElementById(id);
  element.replaceChildren(document.createTextNode(message));
  if (retry) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-ghost";
    button.textContent = "再試行";
    button.addEventListener("click", retry);
    element.appendChild(button);
  }
}

export function initQueue() {
  const form = document.getElementById("add-url-form");
  bindMediaDefaults(
    form.elements.namedItem("audio_format"),
    form.elements.namedItem("audio_quality"),
    document.getElementById("download-media-summary"),
    document.getElementById("url-error"),
  );
  renderUrlList();
  renderJobList();
  startSSE();
  document.addEventListener("url-sources-updated", () => {
    renderUrlList();
    renderJobList();
  });
  form.addEventListener("submit", handleAddUrl);
  document.addEventListener("visibilitychange", resume);
  window.addEventListener("pagehide", () => {
    pageAway = true;
    stopSSE();
  });
  window.addEventListener("pageshow", () => {
    pageAway = false;
    resume();
  });
}

function resume() {
  if (document.hidden || pageAway) {
    stopSSE();
  } else if (!es) {
    renderUrlList();
    renderJobList();
    startSSE();
  }
}

function stopSSE() {
  if (es) es.close();
  es = null;
}

async function handleAddUrl(e) {
  e.preventDefault();
  const form = e.target;
  const button = form.querySelector('[type="submit"]');
  if (button.disabled) return;
  const url = form.elements.namedItem("url").value.trim();
  const errEl = document.getElementById("url-error");
  errEl.textContent = "";
  button.disabled = true;
  try {
    await loadDownloadPreferences();
    const audio_format = form.elements.namedItem("audio_format").value;
    const audio_quality = form.elements.namedItem("audio_quality").value;
    await api.addUrl({ url, audio_format, audio_quality, sync_enabled: true });
    if (form.elements.namedItem("url").value.trim() === url)
      form.elements.namedItem("url").value = "";
    renderUrlList();
    renderJobList();
  } catch (err) {
    errEl.textContent = err.message;
  } finally {
    button.disabled = false;
  }
}

// Keyed reconciliation keeps unaffected controls, focus and error messages alive.
function reconcile(container, records, key, create, update, empty) {
  const rows = new Map(
    [...container.children]
      .filter((row) => row.dataset[key])
      .map((row) => [Number(row.dataset[key]), row]),
  );
  container.querySelector(".empty-state")?.remove();
  let position = container.firstElementChild;
  for (const record of records) {
    const row = rows.get(record.id) || create(record);
    rows.delete(record.id);
    update(row, record);
    if (row !== position) container.insertBefore(row, position);
    position = row.nextElementSibling;
  }
  for (const row of rows.values()) row.remove();
  if (!records.length) {
    const message = document.createElement("div");
    message.className = "empty-state";
    message.textContent = empty;
    container.appendChild(message);
  }
}

async function renderUrlList() {
  const container = document.getElementById("url-list");
  const request = ++urlListRequest;
  try {
    const urls = await api.listUrls();
    if (request !== urlListRequest) return;
    reconcile(
      container,
      urls,
      "urlId",
      buildUrl,
      (row, source) => {
        row.querySelector(".url-item-title").textContent =
          source.title || source.url;
        const type =
          { video: "動画", playlist: "プレイリスト", channel: "チャンネル" }[
            source.url_type
          ] || source.url_type;
        row.querySelector(".url-item-meta").textContent =
          `${type} · ${source.audio_format.toUpperCase()}/${source.audio_quality === "best" ? "最高品質" : source.audio_quality + "kbps"} · ${source.sync_enabled ? "自動取得ON" : "自動取得OFF"}`;
        row.querySelector(".delete-url").disabled = busyUrls.has(source.id);
      },
      "登録済みのURLはありません",
    );
    notice("url-list-status");
  } catch (error) {
    if (request === urlListRequest)
      notice(
        "url-list-status",
        `URL一覧を取得できません: ${error.message}`,
        renderUrlList,
      );
  }
}

function buildUrl(source) {
  const row = document.createElement("div");
  row.className = "url-item";
  row.dataset.urlId = source.id;
  row.innerHTML =
    '<div class="url-item-info"><div class="url-item-title"></div><div class="url-item-meta"></div><div class="row-action-feedback error-msg" role="status" aria-live="polite"></div></div><div class="url-item-actions"><button class="btn btn-ghost delete-url" type="button" title="保存済みファイルを残してURLの登録を解除">登録解除</button></div>';
  row.querySelector(".delete-url").addEventListener("click", async () => {
    if (busyUrls.has(source.id)) return;
    busyUrls.add(source.id);
    const button = row.querySelector("button");
    const feedback = row.querySelector(".row-action-feedback");
    button.disabled = true;
    feedback.textContent = "登録を解除中…";
    try {
      await api.deleteUrl(source.id, false);
      ++urlListRequest;
      row.remove();
      await Promise.all([renderUrlList(), renderJobList()]);
    } catch (error) {
      feedback.textContent = `登録解除に失敗しました: ${error.message}`;
    } finally {
      busyUrls.delete(source.id);
      button.disabled = false;
    }
  });
  return row;
}

async function renderJobList() {
  const container = document.getElementById("job-list");
  const request = ++jobListRequest;
  fetchingJobs = true;
  try {
    const result = await api.listQueue("pending,downloading,failed");
    if (request !== jobListRequest) return;
    jobs = result;
    reconcile(
      container,
      jobs,
      "jobId",
      buildJob,
      updateJob,
      "処理中のダウンロードはありません",
    );
    notice("queue-status");
  } catch (error) {
    if (request === jobListRequest)
      notice(
        "queue-status",
        `キューを取得できません: ${error.message}`,
        renderJobList,
      );
  } finally {
    if (request === jobListRequest) fetchingJobs = false;
  }
}

function updateProgress(row, job) {
  const badge = row.querySelector(".status-badge");
  badge.className = `status-badge status-${job.status}`;
  badge.textContent = labels[job.status] || job.status;
  const pct = percent(job.progress_pct);
  row.querySelector(".progress-fill").style.width = `${pct}%`;
  row.querySelector(".progress-bar").setAttribute("aria-valuenow", String(pct));
}

function updateJob(row, job) {
  row.querySelector(".job-title").textContent = job.title || job.youtube_id;
  row.querySelector(".job-title").title = job.title || job.youtube_id;
  row.querySelector(".job-error").textContent =
    job.status === "failed" ? job.error_message || "" : "";
  row.querySelector(".retry-job").hidden = job.status !== "failed";
  for (const button of row.querySelectorAll("button"))
    button.disabled = busyJobs.has(job.id);
  updateProgress(row, job);
}

function buildJob(job) {
  const row = document.createElement("div");
  row.className = "job-item";
  row.dataset.jobId = job.id;
  row.innerHTML =
    '<div class="job-header"><span class="job-title"></span><span class="status-badge"></span><button class="btn btn-ghost retry-job" type="button">再試行</button><button class="btn btn-ghost cancel-job" type="button" aria-label="このダウンロードを取り消す" title="ダウンロードを取り消す">✕</button></div><div class="progress-bar" role="progressbar" aria-label="ダウンロードの進捗" aria-valuemin="0" aria-valuemax="100"><div class="progress-fill"></div></div><div class="job-error error-msg"></div><div class="row-action-feedback error-msg" role="status" aria-live="polite"></div>';
  row
    .querySelector(".retry-job")
    .addEventListener("click", () => actOnJob(row, job.id, "retry"));
  row
    .querySelector(".cancel-job")
    .addEventListener("click", () => actOnJob(row, job.id, "cancel"));
  return row;
}

async function actOnJob(row, id, action) {
  if (busyJobs.has(id)) return;
  busyJobs.add(id);
  const feedback = row.querySelector(".row-action-feedback");
  for (const button of row.querySelectorAll("button")) button.disabled = true;
  row.setAttribute("aria-busy", "true");
  feedback.textContent = action === "retry" ? "再試行を依頼中…" : "取消中…";
  try {
    const result =
      action === "retry" ? await api.retryJob(id) : await api.cancelJob(id);
    ++jobListRequest;
    if (action === "cancel") {
      jobs = jobs.filter((job) => job.id !== id);
      row.remove();
    } else if (result) {
      jobs = jobs.map((job) => (job.id === id ? result : job));
      updateJob(row, result);
    }
    feedback.textContent = "";
    await renderJobList();
  } catch (error) {
    feedback.textContent = `${action === "retry" ? "再試行" : "取消"}に失敗しました: ${error.message}`;
  } finally {
    busyJobs.delete(id);
    row.removeAttribute("aria-busy");
    for (const button of row.querySelectorAll("button"))
      button.disabled = false;
  }
}

function startSSE() {
  if (document.hidden || pageAway || es) return;
  let refreshing = false;
  let reconnecting = false;
  const stream = subscribeQueueEvents((events) => {
    if (es !== stream || !Array.isArray(events)) return;
    notice("queue-connection-status");
    const container = document.getElementById("job-list");
    const activeIds = new Set(events.map((event) => event.job_id));
    const changed =
      events.some((event) => !jobs.some((job) => job.id === event.job_id)) ||
      jobs.some(
        (job) =>
          ["pending", "downloading"].includes(job.status) &&
          !activeIds.has(job.id),
      ) ||
      events.some((event) => ["complete", "failed"].includes(event.status));
    for (const event of events) {
      const row = container.querySelector(
        `[data-job-id="${Number(event.job_id)}"]`,
      );
      if (row)
        updateProgress(row, { ...event, progress_pct: event.progress_pct });
      const job = jobs.find((job) => job.id === event.job_id);
      if (job)
        Object.assign(job, {
          status: event.status,
          progress_pct: event.progress_pct,
        });
    }
    if (changed && !refreshing && !fetchingJobs) {
      refreshing = true;
      renderJobList().finally(() => {
        refreshing = false;
      });
    }
  });
  es = stream;
  stream.onerror = () => {
    if (es === stream) {
      reconnecting = true;
      notice(
        "queue-connection-status",
        "進捗に再接続中です。現在の表示は最後に取得した状態です。",
      );
    }
  };
  stream.onopen = () => {
    if (es !== stream) return;
    notice("queue-connection-status");
    if (reconnecting) renderJobList();
    reconnecting = false;
  };
}
