import { api } from "./api.js";
import { player } from "./player.js";

let tracks = [];

export function initLibrary() {
  loadTracks();
  document.getElementById("search-input").addEventListener("input", debounce(onSearch, 300));
}

async function loadTracks(params = {}) {
  const container = document.getElementById("track-grid");
  container.innerHTML = '<div class="empty-state">Loading…</div>';
  try {
    tracks = await api.listTracks({ limit: 100, ...params });
    renderTracks();
  } catch {
    container.innerHTML = '<div class="empty-state">Failed to load tracks</div>';
  }
}

function renderTracks() {
  const container = document.getElementById("track-grid");
  if (!tracks.length) {
    container.innerHTML = '<div class="empty-state">No tracks yet. Add a YouTube URL to get started.</div>';
    return;
  }
  container.innerHTML = "";
  for (let i = 0; i < tracks.length; i++) {
    const t = tracks[i];
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
      player.play(tracks, i);
    });

    container.appendChild(item);
  }

  container.querySelectorAll(".delete-track").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm("Delete this track?")) return;
      await api.deleteTrack(Number(btn.dataset.id), true).catch(() => {});
      loadTracks();
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
  loadTracks();
}
