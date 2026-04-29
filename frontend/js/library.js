import { api } from "./api.js";
import { player } from "./player.js";

const PAGE_SIZE = 50;
let tracks = [];
let currentOffset = 0;
let currentParams = {};
let hasMore = false;

export function initLibrary() {
  loadTracks();
  document.getElementById("search-input").addEventListener("input", debounce(onSearch, 300));
}

async function loadTracks(params = {}, append = false) {
  const container = document.getElementById("track-grid");
  if (!append) {
    container.innerHTML = '<div class="empty-state">Loading…</div>';
    tracks = [];
    currentOffset = 0;
    currentParams = params;
  }

  try {
    const page = await api.listTracks({ limit: PAGE_SIZE, offset: currentOffset, ...currentParams });
    hasMore = page.length === PAGE_SIZE;
    currentOffset += page.length;
    if (append) {
      appendTracks(page, container);
    } else {
      tracks = page;
      renderAll(container);
    }
  } catch {
    if (!append) container.innerHTML = '<div class="empty-state">Failed to load tracks</div>';
  }
}

function renderAll(container) {
  if (!tracks.length) {
    container.innerHTML = '<div class="empty-state">No tracks yet. Add a YouTube URL to get started.</div>';
    return;
  }
  container.innerHTML = "";
  for (let i = 0; i < tracks.length; i++) {
    container.appendChild(buildItem(tracks[i], i));
  }
  bindDeleteButtons(container);
  renderLoadMore(container);
}

function appendTracks(newTracks, container) {
  const btn = container.querySelector(".load-more-btn");
  if (btn) btn.remove();
  const startIndex = tracks.length;
  tracks = tracks.concat(newTracks);
  for (let i = startIndex; i < tracks.length; i++) {
    container.appendChild(buildItem(tracks[i], i));
  }
  bindDeleteButtons(container);
  renderLoadMore(container);
}

function renderLoadMore(container) {
  if (!hasMore) return;
  const btn = document.createElement("button");
  btn.className = "btn btn-ghost load-more-btn";
  btn.textContent = "もっと読み込む";
  btn.addEventListener("click", () => loadTracks(currentParams, true));
  container.appendChild(btn);
}

function buildItem(t, index) {
  const item = document.createElement("div");
  item.className = "track-item";
  item.dataset.trackId = t.id;

  const thumbHTML = t.thumbnail_url
    ? `<img class="track-thumb" src="${t.thumbnail_url}" alt="" loading="lazy">`
    : `<div class="track-thumb-placeholder">♪</div>`;

  item.innerHTML = `
    ${thumbHTML}
    <div class="track-info">
      <div class="track-title">${escHtml(t.title)}</div>
      <div class="track-artist">${escHtml(t.artist || "Unknown")}</div>
    </div>
    <div class="track-actions">
      <span class="track-duration">${fmt(t.duration_secs)}</span>
      <a class="btn btn-ghost" href="${t.download_url}" download title="Download">↓</a>
      <button class="btn btn-ghost delete-track" data-id="${t.id}" title="Delete">🗑</button>
    </div>
  `;

  item.addEventListener("click", (e) => {
    if (e.target.closest(".track-actions a, .track-actions button")) return;
    player.play(tracks, index);
  });

  return item;
}

function bindDeleteButtons(container) {
  container.querySelectorAll(".delete-track").forEach((btn) => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm("Delete this track?")) return;
      await api.deleteTrack(Number(btn.dataset.id), true).catch(() => {});
      loadTracks(currentParams);
    });
  });
}

function onSearch(e) {
  loadTracks({ search: e.target.value.trim() });
}

function fmt(secs) {
  if (!secs) return "";
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function debounce(fn, delay) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), delay); };
}

function escHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export function refreshLibrary() {
  loadTracks(currentParams);
}
