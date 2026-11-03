import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { JSDOM } from "jsdom";
import { api } from "../../frontend/js/api.js";

const tick = () => new Promise((resolve) => setImmediate(resolve));
async function until(fn) {
  for (let i = 0; i < 100; i++) {
    if (fn()) return;
    await tick();
  }
  assert.ok(fn());
}
const track = (id) => ({ id, title: `track ${id}`, download_url: "#" });
async function setup(t) {
  const dom = new JSDOM(
    await readFile(
      new URL("../../frontend/index.html", import.meta.url),
      "utf8",
    ),
    { url: "http://localhost/" },
  );
  const keys = ["window", "document", "localStorage", "Audio", "confirm"];
  const old = Object.fromEntries(
    keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]),
  );
  for (const key of ["window", "document", "localStorage"])
    Object.defineProperty(globalThis, key, {
      value: dom.window[key],
      configurable: true,
    });
  Object.defineProperty(globalThis, "Audio", {
    value: class extends EventTarget {},
    configurable: true,
  });
  const original = api.listTracks;
  const originalDelete = api.deleteTrack;
  let remove = async () => {};
  api.deleteTrack = (...args) => remove(...args);
  globalThis.confirm = () => true;
  const pending = [];
  api.listTracks = (params, options) =>
    new Promise((resolve, reject) =>
      pending.push({ params, options, resolve, reject }),
    );
  t.after(() => {
    api.listTracks = original;
    api.deleteTrack = originalDelete;
    dom.window.close();
    for (const key of keys) {
      if (old[key]) Object.defineProperty(globalThis, key, old[key]);
      else delete globalThis[key];
    }
  });
  const { initLibrary } = await import(
    `../../frontend/js/library.js?race=${t.name}`
  );
  initLibrary();
  return {
    pending,
    setDelete: (fn) => (remove = fn),
    search: async (value) => {
      const input = document.querySelector("#search-input");
      input.value = value;
      input.dispatchEvent(new dom.window.Event("input"));
      await new Promise((resolve) => setTimeout(resolve, 320));
    },
  };
}

test("new search ignores older successful responses and preserves pagination offset", async (t) => {
  const { pending, search } = await setup(t);
  await search("new");
  pending[1].resolve(Array.from({ length: 50 }, (_, i) => track(i + 100)));
  await until(() => document.querySelectorAll(".track-item").length === 50);
  pending[0].resolve([track(1)]);
  await tick();
  assert.equal(document.querySelector(".track-item").dataset.trackId, "100");
  document.querySelector(".load-more-btn").click();
  assert.deepEqual(pending[2].params, { limit: 50, offset: 50, search: "new" });
  pending[2].resolve([]);
  await tick();
});

test("older failed response cannot replace current search results", async (t) => {
  const { pending, search } = await setup(t);
  await search("new");
  pending[1].resolve([track(2)]);
  await until(() => document.querySelector(".track-item"));
  pending[0].reject(new Error("old failure"));
  await tick();
  assert.equal(document.querySelector(".track-item").dataset.trackId, "2");
});

test("load more blocks duplicate requests and cannot append to a newer search", async (t) => {
  const { pending, search } = await setup(t);
  pending[0].resolve(Array.from({ length: 50 }, (_, i) => track(i)));
  await until(() => document.querySelector(".load-more-btn"));
  const button = document.querySelector(".load-more-btn");
  button.click();
  button.click();
  assert.equal(pending.length, 2);
  await search("new");
  pending[2].resolve([track(100)]);
  await until(
    () => document.querySelector(".track-item")?.dataset.trackId === "100",
  );
  pending[1].resolve([track(50)]);
  await tick();
  assert.equal(document.querySelectorAll(".track-item").length, 1);
  assert.equal(document.querySelector(".track-item").dataset.trackId, "100");
});

test("deleting from a loaded second page keeps rows, focus, scroll and the next offset", async (t) => {
  const q = await setup(t);
  q.pending[0].resolve(Array.from({ length: 50 }, (_, i) => track(i + 1)));
  await until(() => document.querySelector(".load-more-btn"));
  document.querySelector(".load-more-btn").click();
  q.pending[1].resolve(Array.from({ length: 50 }, (_, i) => track(i + 51)));
  await until(() => document.querySelectorAll(".track-item").length === 100);
  const container = document.querySelector("#track-grid"),
    keep = document.querySelector('[data-track-id="75"]');
  container.scrollTop = 320;
  keep.querySelector(".preview-track").focus();
  document.querySelector('[data-track-id="65"] .delete-track').click();
  await until(() => document.querySelectorAll(".track-item").length === 99);
  assert.equal(q.pending.length, 2);
  assert.equal(document.querySelector('[data-track-id="75"]'), keep);
  assert.equal(document.activeElement, keep.querySelector(".preview-track"));
  assert.equal(container.scrollTop, 320);
  document.querySelector(".load-more-btn").click();
  assert.equal(q.pending[2].params.offset, 99);
  q.pending[2].resolve([track(101)]);
  await until(() => document.querySelector('[data-track-id="101"]'));
});

test("deletion discards a page requested at the old offset without skipping the next file", async (t) => {
  const q = await setup(t);
  q.pending[0].resolve(Array.from({ length: 50 }, (_, i) => track(i + 1)));
  await until(() => document.querySelector(".load-more-btn"));
  document.querySelector(".load-more-btn").click();
  document.querySelector('[data-track-id="20"] .delete-track').click();
  await until(() => !document.querySelector('[data-track-id="20"]'));
  assert.equal(q.pending[1].options.signal.aborted, true);
  q.pending[1].resolve([track(51)]);
  await tick();
  assert.equal(document.querySelector('[data-track-id="51"]'), null);
  const more = document.querySelector(".load-more-btn");
  assert.equal(more.disabled, false);
  more.click();
  assert.equal(q.pending[2].params.offset, 49);
  q.pending[2].resolve([track(51)]);
  await until(() => document.querySelector('[data-track-id="51"]'));
});

test("failed load more keeps its place and retries the same offset with visible feedback", async (t) => {
  const q = await setup(t);
  q.pending[0].resolve(Array.from({ length: 50 }, (_, i) => track(i + 1)));
  await until(() => document.querySelector(".load-more-btn"));
  const row = document.querySelector(".track-item"),
    button = document.querySelector(".load-more-btn");
  button.click();
  assert.equal(button.disabled, true);
  q.pending[1].reject(new Error("offline"));
  await until(() => !button.disabled);
  assert.equal(document.querySelector(".track-item"), row);
  assert.match(
    document.querySelector("#library-status").textContent,
    /offline/,
  );
  document.querySelector("#library-status button").click();
  assert.equal(q.pending[2].params.offset, 50);
  q.pending[2].resolve([track(51)]);
  await until(() => document.querySelector('[data-track-id="51"]'));
  assert.equal(document.querySelector("#library-status").textContent, "");
});

test("search keeps the previous list during loading and distinguishes no matches from no files", async (t) => {
  const q = await setup(t);
  q.pending[0].resolve([track(1)]);
  await until(() => document.querySelector(".track-item"));
  const row = document.querySelector(".track-item");
  await q.search("nothing");
  assert.equal(document.querySelector(".track-item"), row);
  assert.match(document.querySelector("#library-status").textContent, /検索中/);
  q.pending[1].resolve([]);
  await until(() => !document.querySelector(".track-item"));
  assert.match(
    document.querySelector("#track-grid").textContent,
    /検索条件に一致/,
  );
});

test("deleting every visible file leaves the next page accessible", async (t) => {
  const q = await setup(t);
  q.pending[0].resolve(Array.from({ length: 50 }, (_, i) => track(i + 1)));
  await until(() => document.querySelector(".load-more-btn"));
  for (const button of document.querySelectorAll(".delete-track"))
    button.click();
  await until(() => document.querySelectorAll(".track-item").length === 0);
  const more = document.querySelector(".load-more-btn");
  assert.ok(more);
  assert.equal(more.disabled, false);
  more.click();
  assert.equal(q.pending[1].params.offset, 0);
  q.pending[1].resolve([track(51)]);
  await until(() => document.querySelector('[data-track-id="51"]'));
  assert.equal(document.querySelector("#track-grid .empty-state"), null);
});

test("a deletion that finishes after a new search removes the matching new row", async (t) => {
  const q = await setup(t);
  let finish;
  q.setDelete(() => new Promise((resolve) => (finish = resolve)));
  q.pending[0].resolve([track(1), track(2)]);
  await until(() => document.querySelector(".track-item"));
  document.querySelector('[data-track-id="1"] .delete-track').click();
  await q.search("new");
  q.pending[1].resolve([track(1)]);
  await until(() => document.querySelectorAll(".track-item").length === 1);
  assert.equal(document.querySelector(".delete-track").disabled, true);
  finish();
  await until(() => !document.querySelector(".track-item"));
  assert.equal(q.pending.length, 2);
});

test("a deletion during search discards a snapshot taken before the deletion", async (t) => {
  const q = await setup(t);
  q.pending[0].resolve([track(1), track(2)]);
  await until(() => document.querySelector(".track-item"));
  await q.search("new");
  document.querySelector('[data-track-id="1"] .delete-track').click();
  await until(() => q.pending.length === 3);
  assert.equal(q.pending[1].options.signal.aborted, true);
  q.pending[1].resolve([track(1)]);
  await tick();
  assert.equal(document.querySelector('[data-track-id="1"]'), null);
  assert.equal(q.pending[2].params.search, "new");
  q.pending[2].resolve([track(2)]);
  await until(
    () => document.querySelector("#library-status").textContent === "",
  );
  assert.equal(document.querySelector(".track-item").dataset.trackId, "2");
});

test("a deletion failure after search appears on the current matching row", async (t) => {
  const q = await setup(t);
  let fail;
  q.setDelete(() => new Promise((_, reject) => (fail = reject)));
  q.pending[0].resolve([track(1), track(2)]);
  await until(() => document.querySelector(".track-item"));
  document.querySelector('[data-track-id="1"] .delete-track').click();
  await q.search("new");
  q.pending[1].resolve([track(1)]);
  await until(() => document.querySelectorAll(".track-item").length === 1);
  fail(new Error("offline"));
  await until(() => !document.querySelector(".delete-track").disabled);
  assert.match(
    document.querySelector(".track-delete-feedback").textContent,
    /offline/,
  );
  assert.equal(document.querySelector(".track-delete-feedback").hidden, false);
  assert.equal(document.querySelector(".retry-delete-track").hidden, false);
});
