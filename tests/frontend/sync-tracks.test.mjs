import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { api } from "../../frontend/js/api.js";
import {
  renderTrackPage,
  pauseTrackPage,
} from "../../frontend/js/sync-tracks.js";
const tick = () => new Promise((r) => setImmediate(r));
async function until(fn) {
  for (let i = 0; i < 100; i++) {
    if (fn()) return;
    await tick();
  }
  assert.ok(fn());
}
const page = (offset = 0, total = 5000) => ({
  offset,
  limit: 50,
  total,
  items: Array.from(
    { length: Math.min(50, Math.max(0, total - offset)) },
    (_, i) => ({ id: offset + i + 1, title: "曲 " + (offset + i + 1) }),
  ),
});
function deferred() {
  let resolve, reject;
  const promise = new Promise((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
}
function setup(t) {
  const dom = new JSDOM('<div id="tracks"></div>');
  const old = Object.getOwnPropertyDescriptor(globalThis, "document");
  Object.defineProperty(globalThis, "document", {
    value: dom.window.document,
    configurable: true,
  });
  const original = api.youtubeSyncTrackPage,
    calls = [],
    container = document.querySelector("#tracks");
  let handler = async (_, params) => page(params.offset);
  api.youtubeSyncTrackPage = (...args) => {
    calls.push(args);
    return handler(...args);
  };
  const render = (items, host) => {
    const old = new Map(
      [...host.children].map((row) => [Number(row.dataset.id), row]),
    );
    host.replaceChildren(
      ...items.map((item) => {
        const row = old.get(item.id) || document.createElement("div");
        row.dataset.id = item.id;
        row.textContent = item.title;
        return row;
      }),
    );
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      host.append(empty);
    }
  };
  t.after(() => {
    pauseTrackPage(container);
    api.youtubeSyncTrackPage = original;
    dom.window.close();
    if (old) Object.defineProperty(globalThis, "document", old);
    else delete globalThis.document;
  });
  return {
    container,
    calls,
    render,
    setHandler: (fn) => (handler = fn),
    load: () => renderTrackPage(1, container, render),
  };
}

test("large playlists render only 50 rows and poll the selected page without growing the DOM", async (t) => {
  const s = setup(t);
  await s.load();
  assert.equal(
    s.container.querySelector(".sync-track-results").children.length,
    50,
  );
  assert.match(s.container.textContent, /1–50 \/ 5000曲/);
  s.container.querySelector(".next-track-page").click();
  await until(() => s.container.textContent.includes("51–100"));
  const rows = s.container.querySelector(".sync-track-results");
  rows.scrollTop = 78;
  const first = rows.firstChild;
  await s.load();
  assert.equal(s.calls.at(-1)[1].offset, 50);
  assert.equal(rows.children.length, 50);
  assert.equal(rows.firstChild, first);
  assert.equal(rows.scrollTop, 78);
  s.container.querySelector(".prev-track-page").click();
  await until(() => s.container.textContent.includes("1–50"));
});

test("search and status reset to page one and stale requests cannot restore older results", async (t) => {
  const s = setup(t);
  await s.load();
  s.container.querySelector(".next-track-page").click();
  await until(() => s.calls.length === 2);
  await tick();
  const old = deferred();
  s.setHandler(() => old.promise);
  const pending = s.load();
  const input = s.container.querySelector("input");
  input.value = "new";
  input.dispatchEvent(new document.defaultView.Event("input"));
  assert.equal(s.calls[2][2].aborted, true);
  s.setHandler(async () => ({
    items: [{ id: 999, title: "New result" }],
    total: 1,
    offset: 0,
    limit: 50,
  }));
  s.container.querySelector("select").value = "failed";
  s.container
    .querySelector("select")
    .dispatchEvent(new document.defaultView.Event("change"));
  await until(() => s.container.textContent.includes("New result"));
  old.resolve(page(50));
  await pending;
  assert.deepEqual(s.calls.at(-1)[1], {
    limit: 50,
    offset: 0,
    search: "new",
    status: "failed",
  });
  assert.equal(
    s.container.querySelector(".sync-track-results").children.length,
    1,
  );
  await s.load();
  assert.equal(s.calls.at(-1)[1].search, "new");
});

test("failed refresh preserves results and retry uses the same page", async (t) => {
  const s = setup(t);
  await s.load();
  const first = s.container.querySelector(".sync-track-results").firstChild;
  s.setHandler(async () => {
    throw Error("offline <script>bad</script>");
  });
  await s.load();
  assert.equal(
    s.container.querySelector(".sync-track-results").firstChild,
    first,
  );
  assert.match(
    s.container.querySelector("[role=status]").textContent,
    /offline/,
  );
  assert.equal(s.container.querySelector("script"), null);
  s.setHandler(async (_, params) => page(params.offset));
  s.container.querySelector(".sync-track-feedback button").click();
  await until(
    () => s.container.querySelector(".sync-track-feedback button").hidden,
  );
  assert.equal(s.calls.at(-1)[1].offset, 0);
});

test("a shrinking playlist clamps to its last remaining page", async (t) => {
  const s = setup(t);
  await s.load();
  s.container.querySelector(".next-track-page").click();
  await until(() => s.container.textContent.includes("51–100"));
  s.setHandler(async (_, params) => page(params.offset, 3));
  await s.load();
  await until(() => s.container.textContent.includes("1–3 / 3曲"));
  assert.equal(s.calls.at(-1)[1].offset, 0);
  assert.equal(s.container.querySelector(".next-track-page").disabled, true);
});

test("closing a list cancels an in-flight page and reopening retries it", async (t) => {
  const s = setup(t),
    pending = deferred();
  s.setHandler(() => pending.promise);
  const old = s.load();
  pauseTrackPage(s.container);
  assert.equal(s.calls[0][2].aborted, true);
  pending.resolve(page());
  await old;
  assert.equal(
    s.container.querySelector(".sync-track-results").children.length,
    0,
  );
  s.setHandler(async () => page());
  await s.load();
  assert.equal(
    s.container.querySelector(".sync-track-results").children.length,
    50,
  );
});

test("removing all tracks resets an empty second page to the first page", async (t) => {
  const s = setup(t);
  await s.load();
  s.container.querySelector(".next-track-page").click();
  await until(() => s.container.textContent.includes("51–100"));
  s.setHandler(async (_, params) => page(params.offset, 0));
  await s.load();
  assert.equal(s.container.querySelector(".prev-track-page").disabled, true);
  assert.match(
    s.container.querySelector(".sync-track-count").textContent,
    /0 \/ 0曲/,
  );
});

test("automatic refresh restores keyboard focus on a page control after it becomes enabled", async (t) => {
  const s = setup(t);
  await s.load();
  const button = s.container.querySelector(".next-track-page");
  button.focus();
  const wait = deferred();
  s.setHandler(() => wait.promise);
  const loading = s.load();
  button.blur();
  wait.resolve(page());
  await loading;
  assert.equal(document.activeElement, button);
});
