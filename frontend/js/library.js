import { api } from "./api.js";
import { player } from "./player.js";

const PAGE_SIZE = 50;
let tracks = [];
let currentOffset = 0;
let currentParams = {};
let hasMore = false;
let listGeneration = 0;
let loadingMore = false;
let displayedGeneration = 0;
let controller;
const deleting = new Set();

function feedback(message = "", retry) {
  const notice = document.getElementById("library-status");
  notice.replaceChildren(document.createTextNode(message));
  if (retry) {
    const button = document.createElement("button");
    button.className = "btn btn-ghost";
    button.textContent = "再試行";
    button.addEventListener("click", retry);
    notice.appendChild(button);
  }
}

export function initLibrary() {
  loadTracks();
  document
    .getElementById("search-input")
    .addEventListener("input", debounce(onSearch, 300));
}

async function loadTracks(params = {}, append = false) {
  const container = document.getElementById("track-grid");
  if (append && loadingMore) return;
  if (!append) {
    listGeneration++;
    loadingMore = false;
    controller?.abort();
    if (!tracks.length)
      container.innerHTML = '<div class="empty-state">読込中…</div>';
    currentParams = params;
  }
  controller = new AbortController();
  const generation = listGeneration;
  const offset = append ? currentOffset : 0;
  if (append) loadingMore = true;
  container.setAttribute("aria-busy", "true");
  feedback(append ? "続きを読み込み中…" : "ファイルを検索中…");
  const more = container.querySelector(".load-more-btn");
  if (more) more.disabled = true;

  try {
    const page = await api.listTracks(
      { limit: PAGE_SIZE, offset, ...currentParams },
      { signal: controller.signal },
    );
    if (generation !== listGeneration) return;
    hasMore = page.length === PAGE_SIZE;
    currentOffset = offset + page.length;
    if (append) {
      appendTracks(page, container);
    } else {
      tracks = page;
      displayedGeneration = generation;
      renderAll(container);
    }
    feedback();
  } catch (error) {
    if (generation !== listGeneration) return;
    feedback(`ファイルの取得に失敗しました: ${error.message}`, () =>
      loadTracks(currentParams, append),
    );
    if (!tracks.length) container.replaceChildren();
  } finally {
    if (generation === listGeneration) {
      loadingMore = false;
      container.removeAttribute("aria-busy");
      const button = container.querySelector(".load-more-btn");
      if (button) button.disabled = displayedGeneration !== listGeneration;
    }
  }
}

function renderAll(container) {
  if (!tracks.length) {
    container.innerHTML = hasMore
      ? '<div class="empty-state">表示中のファイルを削除しました。続きのファイルを読み込めます。</div>'
      : currentParams.search
        ? '<div class="empty-state">検索条件に一致するファイルはありません</div>'
        : '<div class="empty-state">保存済みのファイルはありません。ダウンロードからURLを追加できます。</div>';
    renderLoadMore(container);
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
  if (newTracks.length) container.querySelector(".empty-state")?.remove();
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
      <button class="btn btn-ghost preview-track" type="button" aria-label="${escHtml(t.title)}を試聴">試聴</button>
      <span class="track-duration">${fmt(t.duration_secs)}</span>
      <a class="btn btn-ghost" href="${t.download_url}" download title="ファイルをダウンロード">↓</a>
      <button class="btn btn-ghost delete-track" data-id="${t.id}" title="削除">🗑</button>
    </div>
    <div class="track-delete-feedback" hidden>
      <span class="track-delete-message" role="status" aria-live="polite"></span>
      <button class="btn btn-ghost retry-delete-track" type="button">削除を再試行</button>
    </div>
  `;

  item
    .querySelector(".preview-track")
    .addEventListener("click", () => player.play([t], 0));

  return item;
}

function bindDeleteButtons(container) {
  container.querySelectorAll(".delete-track").forEach((btn) => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = "1";
    const row = btn.closest(".track-item");
    const notice = row.querySelector(".track-delete-feedback");
    const message = notice.querySelector(".track-delete-message");
    const retry = notice.querySelector("button");
    const id = Number(btn.dataset.id);
    btn.disabled = deleting.has(id);
    const remove = async (event) => {
      event.stopPropagation();
      if (deleting.has(id) || !confirm("このファイルを削除しますか？")) return;
      deleting.add(id);
      btn.disabled = retry.disabled = true;
      row.setAttribute("aria-busy", "true");
      notice.hidden = false;
      notice.classList.remove("error-msg");
      message.textContent = "削除中…";
      retry.hidden = true;
      try {
        await api.deleteTrack(id, true);
        const removedRow = container.querySelector(`[data-track-id="${id}"]`);
        if (!removedRow) return;
        const searchPending =
          displayedGeneration !== listGeneration &&
          container.hasAttribute("aria-busy");
        tracks = tracks.filter((track) => track.id !== id);
        // A concurrent page was requested against the old offset. Discard it
        // and keep the next request aligned with the deleted row.
        if (displayedGeneration === listGeneration) {
          listGeneration++;
          displayedGeneration = listGeneration;
          controller?.abort();
          loadingMore = false;
          currentOffset = Math.max(0, currentOffset - 1);
          container.removeAttribute("aria-busy");
          feedback();
        }
        const focused = removedRow.contains(document.activeElement);
        const next =
          removedRow.nextElementSibling?.querySelector("button") ||
          removedRow.previousElementSibling?.querySelector("button");
        removedRow.remove();
        if (!tracks.length) renderAll(container);
        const more = container.querySelector(".load-more-btn");
        if (more) more.disabled = displayedGeneration !== listGeneration;
        if (focused)
          (next || document.getElementById("search-input")).focus({
            preventScroll: true,
          });
        if (searchPending) loadTracks(currentParams);
      } catch (error) {
        const currentNotice =
          container.querySelector(
            `[data-track-id="${id}"] .track-delete-feedback`,
          ) || notice;
        currentNotice.hidden = false;
        currentNotice.querySelector(".track-delete-message").textContent =
          "削除に失敗しました: " + error.message;
        currentNotice.classList.add("error-msg");
        currentNotice.querySelector("button").hidden = false;
      } finally {
        deleting.delete(id);
        btn.disabled = retry.disabled = false;
        row.removeAttribute("aria-busy");
        const current = container.querySelector(`[data-track-id="${id}"]`);
        if (current) current.querySelector(".delete-track").disabled = false;
      }
    };
    btn.addEventListener("click", remove);
    retry.addEventListener("click", remove);
  });
}

function onSearch(e) {
  loadTracks({ search: e.target.value.trim() });
}

function fmt(secs) {
  if (!secs) return "";
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60)
    .toString()
    .padStart(2, "0");
  return `${m}:${s}`;
}

function debounce(fn, delay) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), delay);
  };
}

function escHtml(str) {
  return String(str).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
}

export function refreshLibrary() {
  loadTracks(currentParams);
}
