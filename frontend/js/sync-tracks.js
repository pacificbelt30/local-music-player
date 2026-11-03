import { api } from "./api.js";

const PAGE_SIZE = 50;
const browsers = new WeakMap();

function browser(syncId, container, renderRows) {
  let state = browsers.get(container);
  if (state) return state;
  container.innerHTML =
    '<form class="sync-track-toolbar"><label><span>タイトル・アーティスト</span><input type="search" maxlength="200" placeholder="このプレイリスト内を検索" aria-label="同期プレイリスト内の曲を検索"></label><label><span>状態</span><select aria-label="曲の状態で絞り込み"><option value="">すべて</option><option value="active">待機中・取得中</option><option value="failed">失敗</option><option value="complete">完了</option><option value="skipped">除外</option></select></label></form><div class="sync-track-feedback" role="status" aria-live="polite"><span></span><button class="btn btn-ghost" type="button" hidden>再試行</button></div><div class="sync-track-results"></div><nav class="sync-track-pagination" aria-label="曲一覧のページ"><button class="btn btn-ghost prev-track-page" type="button">前へ</button><span class="sync-track-count" role="status" aria-live="polite"></span><button class="btn btn-ghost next-track-page" type="button">次へ</button></nav>';
  state = {
    offset: 0,
    search: "",
    status: "",
    total: 0,
    pending: false,
    loaded: false,
    dirty: false,
    version: 0,
    container,
    syncId,
    renderRows,
  };
  browsers.set(container, state);
  state.rows = container.querySelector(".sync-track-results");
  state.input = container.querySelector("input");
  state.select = container.querySelector("select");
  state.feedback = container.querySelector(".sync-track-feedback");
  state.message = state.feedback.querySelector("span");
  state.retry = state.feedback.querySelector("button");
  state.previous = container.querySelector(".prev-track-page");
  state.next = container.querySelector(".next-track-page");
  state.count = container.querySelector(".sync-track-count");
  const change = () => {
    clearTimeout(state.timer);
    state.controller?.abort();
    state.version++;
    state.offset = 0;
    state.search = state.input.value.trim();
    state.status = state.select.value;
    state.dirty = true;
    state.pending = false;
    state.previous.disabled = state.next.disabled = true;
  };
  state.input.addEventListener("input", () => {
    change();
    state.timer = setTimeout(() => load(state), 300);
  });
  state.select.addEventListener("change", () => {
    change();
    load(state);
  });
  container.querySelector("form").addEventListener("submit", (event) => {
    event.preventDefault();
    change();
    load(state);
  });
  state.retry.addEventListener("click", () => load(state));
  state.previous.addEventListener("click", () => {
    if (state.pending || state.dirty) return;
    state.offset = Math.max(0, state.offset - PAGE_SIZE);
    state.dirty = true;
    load(state);
  });
  state.next.addEventListener("click", () => {
    if (state.pending || state.dirty) return;
    state.offset += PAGE_SIZE;
    state.dirty = true;
    load(state);
  });
  return state;
}

async function load(state) {
  clearTimeout(state.timer);
  if (!state.container.isConnected) return;
  state.controller?.abort();
  const controller = new AbortController();
  state.controller = controller;
  const version = ++state.version;
  const focusedPageControl = [state.previous, state.next].includes(
    document.activeElement,
  )
    ? document.activeElement
    : null;
  state.pending = true;
  state.previous.disabled = state.next.disabled = state.retry.disabled = true;
  state.rows.setAttribute("aria-busy", "true");
  if (!state.loaded || state.dirty)
    state.message.textContent = "曲を読み込み中…";
  try {
    const params = { limit: PAGE_SIZE, offset: state.offset };
    if (state.search) params.search = state.search;
    if (state.status) params.status = state.status;
    const page = await api.youtubeSyncTrackPage(
      state.syncId,
      params,
      controller.signal,
    );
    if (version !== state.version || !state.container.isConnected) return;
    if (
      !Array.isArray(page.items) ||
      !Number.isInteger(page.total) ||
      page.total < 0
    )
      throw Error("曲一覧を取得できませんでした");
    if (page.total > 0 && state.offset >= page.total) {
      state.offset = Math.floor((page.total - 1) / PAGE_SIZE) * PAGE_SIZE;
      return load(state);
    }
    if (page.total === 0) state.offset = 0;
    const scrollTop = state.dirty ? 0 : state.rows.scrollTop;
    state.renderRows(page.items, state.rows);
    if (!page.items.length)
      state.rows.querySelector(".empty-state").textContent =
        state.search || state.status
          ? "条件に一致する曲はありません"
          : "トラックなし";
    state.rows.scrollTop = scrollTop;
    state.total = page.total;
    state.count.textContent = page.items.length
      ? `${state.offset + 1}–${state.offset + page.items.length} / ${page.total}曲`
      : `0 / ${page.total}曲`;
    state.message.textContent = "";
    state.feedback.classList.remove("error-msg");
    state.retry.hidden = true;
    state.loaded = true;
    state.dirty = false;
  } catch (error) {
    if (version !== state.version || !state.container.isConnected) return;
    state.message.textContent = `更新に失敗しました: ${error.message}`;
    state.feedback.classList.add("error-msg");
    state.retry.hidden = false;
  } finally {
    if (version === state.version) {
      state.pending = false;
      state.retry.disabled = false;
      state.rows.removeAttribute("aria-busy");
      state.previous.disabled = state.dirty || state.offset === 0;
      state.next.disabled =
        state.dirty || state.offset + PAGE_SIZE >= state.total;
      if (focusedPageControl && document.activeElement === document.body) {
        const target = !focusedPageControl.disabled
          ? focusedPageControl
          : !state.previous.disabled
            ? state.previous
            : state.input;
        target.focus({ preventScroll: true });
      }
    }
  }
}

export function renderTrackPage(syncId, container, renderRows) {
  const state = browser(syncId, container, renderRows);
  if (state.pending) return;
  return load(state);
}

export function pauseTrackPage(container) {
  const state = browsers.get(container);
  if (!state) return;
  clearTimeout(state.timer);
  state.controller?.abort();
  state.version++;
  state.pending = false;
  state.rows.removeAttribute("aria-busy");
}
