import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { JSDOM } from "jsdom";
import { api } from "../../frontend/js/api.js";
import {
  initDiscovery,
  initDiscoverySettings,
} from "../../frontend/js/discovery.js";
const tick = () => new Promise((r) => setImmediate(r));
async function until(fn) {
  for (let i = 0; i < 100; i++) {
    if (fn()) return;
    await tick();
  }
  assert.ok(fn());
}
const defaults = (enabled) => ({
  youtube: {
    provider: "youtube",
    enabled: !!enabled,
    region: "JP",
    api_key_set: !!enabled,
  },
  lastfm: {
    provider: "lastfm",
    enabled: !!enabled,
    region: "JP",
    api_key_set: !!enabled,
  },
});
const result = (provider, count = 1) => ({
  provider,
  state: "ready",
  region: "JP",
  cached: false,
  fetched_at: "2026-11-05T12:00:00Z",
  items: Array.from({ length: count }, (_, i) => ({
    id: provider + i,
    title: "曲 " + i,
    artist: "Artist " + i,
    artist_label: provider === "youtube" ? "投稿者" : "アーティスト",
    url:
      provider === "youtube"
        ? "https://www.youtube.com/watch?v=jNQXAC9IVRw"
        : "https://www.last.fm/music/Artist/_/Song",
    youtube_id: provider === "youtube" ? "jNQXAC9IVRw" : null,
  })),
});
async function setup(t, options = {}) {
  const dom = new JSDOM(
    await readFile(
      new URL("../../frontend/index.html", import.meta.url),
      "utf8",
    ),
    { url: "http://localhost/", pretendToBeVisual: true },
  );
  const keys = ["window", "document"];
  const old = Object.fromEntries(
    keys.map((k) => [k, Object.getOwnPropertyDescriptor(globalThis, k)]),
  );
  for (const key of keys)
    Object.defineProperty(globalThis, key, {
      value: dom.window[key],
      configurable: true,
    });
  const original = api.discovery,
    state = {
      config: options.config || defaults(false),
      calls: [],
      handlers: new Map(),
    };
  api.discovery = async (method, path, body, signal) => {
    state.calls.push({ method, path, body, signal });
    const handler = state.handlers.get(method + " " + path);
    if (handler) return handler(body, signal);
    if (path === "/config") return structuredClone(state.config);
    if (method === "PATCH") {
      const p = path.split("/").at(-1);
      const next = {
        ...state.config[p],
        ...Object.fromEntries(
          Object.entries(body).filter(([k]) =>
            ["enabled", "region"].includes(k),
          ),
        ),
      };
      if (body.api_key) next.api_key_set = true;
      if (body.clear_key) {
        next.api_key_set = false;
        next.enabled = false;
      }
      state.config[p] = next;
      return { ...next };
    }
    if (path.endsWith("/test"))
      return { state: "ready", message: "接続できました。" };
    if (path.startsWith("/similar/")) return result("lastfm");
    return result(
      path.includes("youtube") ? "youtube" : "lastfm",
      options.count || 1,
    );
  };
  const view = (id) => {
    for (const panel of document.querySelectorAll(".layout > .panel")) {
      panel.classList.toggle("active", panel.id === id);
      panel.hidden = panel.id !== id;
    }
    document.dispatchEvent(
      new dom.window.CustomEvent("workspace-navigation", {
        detail: { panel: id },
      }),
    );
  };
  t.after(() => {
    dom.window.dispatchEvent(new dom.window.Event("pagehide"));
    api.discovery = original;
    dom.window.close();
    for (const key of keys) {
      if (old[key]) Object.defineProperty(globalThis, key, old[key]);
      else delete globalThis[key];
    }
  });
  return {
    ...state,
    state,
    dom,
    view,
    count: (method, path) =>
      state.calls.filter(
        (c) => c.method === method && (path ? c.path === path : true),
      ).length,
    form: (p) =>
      document.querySelector(`.discovery-config-form[data-provider="${p}"]`),
  };
}

test("settings start with both options off and do not call either provider", async (t) => {
  const s = await setup(t);
  initDiscoverySettings();
  await until(() => !s.form("youtube").querySelector("[type=submit]").disabled);
  assert.equal(s.count("GET", "/config"), 1);
  assert.equal(s.count("POST"), 0);
  assert.equal(s.state.calls.length, 1);
  for (const p of ["youtube", "lastfm"]) {
    const form = s.form(p);
    assert.equal(form.elements.enabled.checked, false);
    assert.equal(form.elements.api_key.value, "");
    assert.equal(form.elements.api_key.type, "password");
    assert.equal(form.querySelector(".discovery-test").disabled, true);
  }
});

test("save sends the key once, clears the input and keeps the providers independent", async (t) => {
  const s = await setup(t);
  initDiscoverySettings();
  await until(() => !s.form("youtube").querySelector("[type=submit]").disabled);
  const form = s.form("youtube");
  let finish;
  s.state.handlers.set(
    "PATCH /config/youtube",
    (body) =>
      new Promise(
        (resolve) =>
          (finish = () =>
            resolve({
              provider: "youtube",
              enabled: body.enabled,
              api_key_set: true,
              region: body.region,
            })),
      ),
  );
  form.elements.api_key.value = "private-key";
  form.elements.enabled.checked = true;
  const submit = () =>
    form.dispatchEvent(new s.dom.window.Event("submit", { cancelable: true }));
  submit();
  submit();
  assert.equal(s.count("PATCH"), 1);
  assert.equal(form.querySelector("[type=submit]").disabled, true);
  finish();
  await until(() => !form.querySelector("[type=submit]").disabled);
  assert.equal(form.elements.api_key.value, "");
  assert.equal(document.body.textContent.includes("private-key"), false);
  assert.equal(s.form("lastfm").elements.enabled.checked, false);
  s.state.handlers.delete("PATCH /config/youtube");
  submit();
  await until(() => s.count("PATCH") === 2);
  assert.equal("api_key" in s.state.calls.at(-1).body, false);
});

test("saved keys can be tested and deleting one disables only that provider", async (t) => {
  const s = await setup(t, { config: defaults(true) });
  initDiscoverySettings();
  await until(
    () => !s.form("youtube").querySelector(".discovery-test").disabled,
  );
  const form = s.form("youtube");
  form.elements.api_key.value = "not-saved";
  form.querySelector(".discovery-test").click();
  await until(() => s.count("POST") === 1);
  await tick();
  assert.match(
    form.querySelector("[role=status]").textContent,
    /接続できました/,
  );
  assert.equal(s.state.calls.find((c) => c.method === "POST").body, undefined);
  window.confirm = () => false;
  form.querySelector(".discovery-clear").click();
  assert.equal(s.count("PATCH"), 0);
  window.confirm = () => true;
  form.querySelector(".discovery-clear").click();
  await until(() => !form.querySelector("[type=submit]").disabled);
  assert.equal(s.state.calls.at(-1).body.clear_key, true);
  assert.equal(form.elements.enabled.checked, false);
  assert.equal(form.elements.api_key.value, "");
  assert.equal(s.form("lastfm").elements.enabled.checked, true);
});

test("save errors retain input, show safe feedback and allow retry", async (t) => {
  const s = await setup(t);
  initDiscoverySettings();
  await until(() => !s.form("lastfm").querySelector("[type=submit]").disabled);
  const form = s.form("lastfm");
  form.elements.api_key.value = "keep-me";
  s.state.handlers.set("PATCH /config/lastfm", () => {
    throw Error("offline <script>bad</script>");
  });
  form.dispatchEvent(new s.dom.window.Event("submit", { cancelable: true }));
  await until(() => !form.querySelector("[type=submit]").disabled);
  assert.equal(form.elements.api_key.value, "keep-me");
  assert.match(form.textContent, /保存に失敗.*offline/);
  assert.equal(form.querySelector("script"), null);
});

test("discovery with both providers disabled performs no external reads", async (t) => {
  const s = await setup(t);
  s.view("discovery-panel");
  initDiscovery();
  await until(() =>
    document.querySelector(".discovery-overview").textContent.includes("任意"),
  );
  assert.equal(s.state.calls.length, 1);
  assert.equal(
    document.querySelector("#discovery-similar-form button").disabled,
    true,
  );
  assert.equal(
    document.querySelector("#player-bar").classList.contains("hidden"),
    true,
  );
});

test("only the enabled source is loaded and rows are shown in bounded batches", async (t) => {
  const settings = defaults(false);
  settings.youtube = { ...settings.youtube, enabled: true, api_key_set: true };
  const s = await setup(t, { config: settings, count: 50 });
  s.view("discovery-panel");
  initDiscovery();
  await until(() => document.querySelectorAll(".discovery-item").length === 20);
  assert.equal(s.count("GET", "/popular/youtube"), 1);
  assert.equal(s.count("GET", "/popular/lastfm"), 0);
  const more = document.querySelector(
    "[data-provider=youtube] .discovery-more",
  );
  more.click();
  assert.equal(document.querySelectorAll(".discovery-item").length, 40);
  more.click();
  assert.equal(document.querySelectorAll(".discovery-item").length, 50);
  assert.equal(more.hidden, true);
  const link = document.querySelector(".discovery-item a");
  assert.equal(link.target, "_blank");
  assert.match(link.rel, /noopener/);
});

test("similar search sends only the selected names and stale results cannot overwrite new input", async (t) => {
  const s = await setup(t, { config: defaults(true) });
  s.view("discovery-panel");
  initDiscovery();
  await until(
    () => !document.querySelector("#discovery-similar-form button").disabled,
  );
  const form = document.querySelector("#discovery-similar-form");
  document.getElementById("discovery-tab-similar").click();
  form.elements.artist.value = "Artist & <x>";
  form.elements.track.value = "Song";
  let finish;
  const path =
    "/similar/lastfm?" +
    new URLSearchParams({ artist: "Artist & <x>", track: "Song" });
  s.state.handlers.set(
    "GET " + path,
    () => new Promise((resolve) => (finish = resolve)),
  );
  form.dispatchEvent(new s.dom.window.Event("submit", { cancelable: true }));
  await until(() => typeof finish === "function");
  const request = s.state.calls.at(-1);
  form.elements.track.value = "new";
  form.elements.track.dispatchEvent(new s.dom.window.Event("input"));
  assert.equal(request.signal.aborted, true);
  finish(result("lastfm"));
  await tick();
  assert.equal(
    document.querySelector("#discovery-similar-results").children.length,
    0,
  );
  form.dispatchEvent(new s.dom.window.Event("submit", { cancelable: true }));
  await until(() => document.querySelector("#discovery-similar-results li"));
  assert.match(
    document.querySelector("#discovery-similar-status").textContent,
    /Last.fm/,
  );
});

test("disabling a source during a request discards its old result immediately", async (t) => {
  const s = await setup(t, { config: defaults(true) });
  let finish;
  s.state.handlers.set(
    "GET /popular/youtube",
    () => new Promise((resolve) => (finish = resolve)),
  );
  s.view("discovery-panel");
  initDiscovery();
  await until(() => typeof finish === "function");
  s.view("settings-panel");
  initDiscoverySettings();
  await until(() => !s.form("youtube").querySelector("[type=submit]").disabled);
  const form = s.form("youtube");
  form.elements.enabled.checked = false;
  form.dispatchEvent(new s.dom.window.Event("submit", { cancelable: true }));
  await until(() => !form.querySelector("[type=submit]").disabled);
  finish(result("youtube"));
  s.view("discovery-panel");
  await tick();
  assert.equal(
    document.querySelector("[data-provider=youtube] .discovery-list").children
      .length,
    0,
  );
  document.getElementById("discovery-tab-youtube").click();
  assert.match(
    document.querySelector("[data-provider=youtube]").textContent,
    /有効にすると/,
  );
});

test("page restoration cancels old reads and starts one fresh request", async (t) => {
  const settings = defaults(false);
  settings.youtube = { ...settings.youtube, enabled: true, api_key_set: true };
  const s = await setup(t, { config: settings });
  let finish;
  s.state.handlers.set(
    "GET /popular/youtube",
    () => new Promise((resolve) => (finish = resolve)),
  );
  s.view("discovery-panel");
  initDiscovery();
  await until(() => typeof finish === "function");
  const request = s.state.calls.at(-1);
  window.dispatchEvent(new s.dom.window.Event("pagehide"));
  assert.equal(request.signal.aborted, true);
  finish(result("youtube"));
  await tick();
  s.state.handlers.delete("GET /popular/youtube");
  window.dispatchEvent(new s.dom.window.Event("pageshow"));
  await until(() => document.querySelector(".discovery-item"));
  assert.equal(s.count("GET", "/popular/youtube"), 2);
});

test("source tabs load only the selected provider and preserve its expanded list", async (t) => {
  const s = await setup(t, { config: defaults(true), count: 50 });
  s.view("discovery-panel");
  initDiscovery();
  await until(() => document.querySelector("[data-provider=youtube] li"));
  assert.equal(s.count("GET", "/popular/lastfm"), 0);
  document.querySelector("[data-provider=youtube] .discovery-more").click();
  document.getElementById("discovery-tab-lastfm").click();
  await until(() => document.querySelector("[data-provider=lastfm] li"));
  assert.equal(document.querySelector("[data-provider=youtube]").hidden, true);
  assert.equal(document.querySelector("[data-provider=lastfm]").hidden, false);
  const first = document.querySelector("[data-provider=youtube] li");
  document.getElementById("discovery-tab-youtube").click();
  assert.equal(document.querySelector("[data-provider=youtube] li"), first);
  assert.equal(
    document.querySelectorAll("[data-provider=youtube] li").length,
    40,
  );
  assert.equal(s.count("GET", "/popular/youtube"), 1);
  assert.equal(s.count("GET", "/popular/lastfm"), 1);
  const yt = document.getElementById("discovery-tab-youtube");
  yt.dispatchEvent(
    new s.dom.window.KeyboardEvent("keydown", { key: "End", bubbles: true }),
  );
  assert.equal(document.activeElement.id, "discovery-tab-similar");
  assert.equal(document.activeElement.getAttribute("aria-selected"), "true");
  assert.equal(document.querySelectorAll("[role=tab][tabindex='0']").length, 1);
  assert.equal(document.getElementById("discovery-similar").hidden, false);
});

test("the only configured provider opens automatically and unavailable sources link to their key form", async (t) => {
  const settings = defaults(false);
  settings.lastfm = { ...settings.lastfm, enabled: true, api_key_set: true };
  const s = await setup(t, { config: settings });
  s.view("discovery-panel");
  initDiscovery();
  await until(() => document.querySelector("[data-provider=lastfm] li"));
  assert.equal(
    document
      .getElementById("discovery-tab-lastfm")
      .getAttribute("aria-selected"),
    "true",
  );
  assert.equal(s.count("GET", "/popular/youtube"), 0);
  document.getElementById("discovery-tab-youtube").click();
  const link = document.querySelector(
    "[data-provider=youtube] [data-navigate]",
  );
  assert.equal(link.dataset.navigate, "settings-panel");
  assert.equal(link.dataset.focusTarget, "discovery-config-youtube");
  assert.equal(s.count("GET", "/popular/youtube"), 0);
});

test("a chart track starts similar discovery without retyping and preserves the selected seed", async (t) => {
  const s = await setup(t, { config: defaults(true) });
  s.view("discovery-panel");
  initDiscovery();
  await until(() => document.querySelector("[data-provider=youtube] li"));
  assert.equal(
    document.querySelector("[data-provider=youtube] .discovery-seed"),
    null,
  );
  document.getElementById("discovery-tab-lastfm").click();
  await until(() =>
    document.querySelector("[data-provider=lastfm] .discovery-seed"),
  );
  document.querySelector("[data-provider=lastfm] .discovery-seed").click();
  await until(() => document.querySelector("#discovery-similar-results li"));
  const form = document.getElementById("discovery-similar-form");
  assert.equal(form.elements.artist.value, "Artist 0");
  assert.equal(form.elements.track.value, "曲 0");
  assert.equal(document.getElementById("discovery-similar").hidden, false);
  assert.equal(
    s.count(
      "GET",
      "/similar/lastfm?" +
        new URLSearchParams({ artist: "Artist 0", track: "曲 0" }),
    ),
    1,
  );
  assert.match(
    document.getElementById("discovery-similar-status").textContent,
    /曲 0.*Artist 0/,
  );
  assert.equal(s.count("POST"), 0);
});

test("changing views cancels an unfinished similar lookup and late results stay discarded", async (t) => {
  const s = await setup(t, { config: defaults(true) });
  s.view("discovery-panel");
  initDiscovery();
  await until(() => document.querySelector("[data-provider=youtube] li"));
  document.getElementById("discovery-tab-lastfm").click();
  await until(() =>
    document.querySelector("[data-provider=lastfm] .discovery-seed"),
  );
  let finish;
  const path =
    "/similar/lastfm?" +
    new URLSearchParams({ artist: "Artist 0", track: "曲 0" });
  s.state.handlers.set(
    "GET " + path,
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  document.querySelector("[data-provider=lastfm] .discovery-seed").click();
  await until(() => finish);
  const request = s.state.calls.at(-1);
  document.getElementById("discovery-tab-youtube").click();
  assert.equal(request.signal.aborted, true);
  finish(result("lastfm"));
  await tick();
  document.getElementById("discovery-tab-similar").click();
  assert.equal(
    document.querySelectorAll("#discovery-similar-results li").length,
    0,
  );
  assert.equal(
    document.querySelector("#discovery-similar-form [type=submit]").disabled,
    false,
  );
  assert.match(
    document.getElementById("discovery-similar-status").textContent,
    /もう一度/,
  );
});

test("returning after the cache expires refreshes the visible list without rebuilding existing rows", async (t) => {
  const s = await setup(t, { config: defaults(true) });
  const realNow = Date.now;
  let time = Date.parse("2026-11-05T12:00:00Z");
  Date.now = () => time;
  t.after(() => {
    Date.now = realNow;
  });
  s.state.handlers.set("GET /popular/youtube", () => ({
    ...result("youtube"),
    expires_at: new Date(time + 60000).toISOString(),
  }));
  s.view("discovery-panel");
  initDiscovery();
  await until(() => document.querySelector("[data-provider=youtube] li"));
  const row = document.querySelector("[data-provider=youtube] li");
  s.view("settings-panel");
  s.view("discovery-panel");
  await tick();
  assert.equal(s.count("GET", "/popular/youtube"), 1);
  s.view("settings-panel");
  time += 61000;
  s.view("discovery-panel");
  await until(() => s.count("GET", "/popular/youtube") === 2);
  await tick();
  assert.equal(document.querySelector("[data-provider=youtube] li"), row);
  assert.equal(s.count("GET", "/popular/lastfm"), 0);
});

test("key errors offer direct repair and a successful save links back to that source", async (t) => {
  const s = await setup(t, { config: defaults(true) });
  s.state.handlers.set("GET /popular/youtube", () => ({
    ...result("youtube", 0),
    state: "error",
    error_code: "key_rejected",
    message: "キーを確認してください。",
  }));
  s.view("discovery-panel");
  initDiscovery();
  await until(() =>
    document.querySelector("[data-provider=youtube] .discovery-feedback a"),
  );
  assert.equal(
    document.querySelector("[data-provider=youtube] .discovery-feedback a")
      .dataset.focusTarget,
    "discovery-config-youtube",
  );
  s.view("settings-panel");
  initDiscoverySettings();
  await until(() => !s.form("lastfm").querySelector("[type=submit]").disabled);
  s.form("lastfm").dispatchEvent(
    new s.dom.window.Event("submit", { cancelable: true }),
  );
  await until(() => s.form("lastfm").querySelector("[data-navigate]"));
  const link = s.form("lastfm").querySelector("[data-navigate]");
  link.addEventListener("click", (event) => event.preventDefault());
  link.click();
  s.view("discovery-panel");
  await until(() => document.querySelector("[data-provider=lastfm] li"));
  assert.equal(
    document
      .getElementById("discovery-tab-lastfm")
      .getAttribute("aria-selected"),
    "true",
  );
});

test("a short provider cooldown retries once without losing the current action", async (t) => {
  const s = await setup(t, { config: defaults(true) });
  const realSetTimeout = window.setTimeout.bind(window);
  const waits = [];
  window.setTimeout = (fn, delay) => {
    waits.push(delay);
    return realSetTimeout(fn, 0);
  };
  let attempts = 0;
  s.state.handlers.set("GET /popular/youtube", () =>
    ++attempts === 1
      ? {
          ...result("youtube", 0),
          state: "error",
          error_code: "cooldown",
          message: "少し待ってください",
        }
      : result("youtube"),
  );
  s.view("discovery-panel");
  initDiscovery();
  await until(() => document.querySelector("[data-provider=youtube] li"));
  assert.equal(attempts, 2);
  assert.deepEqual(waits, [2100]);
  assert.equal(
    document.querySelector("[data-provider=youtube]").getAttribute("aria-busy"),
    null,
  );
  assert.equal(
    document.querySelector("[data-provider=youtube] .error-msg"),
    null,
  );
});

test("leaving during a cooldown cancels its retry and preserves the other view", async (t) => {
  const s = await setup(t, { config: defaults(true) });
  let waiting;
  window.setTimeout = (fn) => {
    waiting = fn;
    return 123;
  };
  const cleared = [];
  window.clearTimeout = (id) => cleared.push(id);
  s.state.handlers.set("GET /popular/youtube", () => ({
    ...result("youtube", 0),
    state: "error",
    error_code: "cooldown",
  }));
  s.view("discovery-panel");
  initDiscovery();
  await until(() => waiting);
  document.getElementById("discovery-tab-lastfm").click();
  await until(() => document.querySelector("[data-provider=lastfm] li"));
  assert.deepEqual(cleared, [123]);
  assert.equal(s.count("GET", "/popular/youtube"), 1);
  assert.equal(
    document
      .getElementById("discovery-tab-lastfm")
      .getAttribute("aria-selected"),
    "true",
  );
});

test("quota errors never retry and a persistent cooldown stops after one retry", async (t) => {
  const s = await setup(t, { config: defaults(true) });
  const realSetTimeout = window.setTimeout.bind(window);
  window.setTimeout = (fn) => realSetTimeout(fn, 0);
  s.state.handlers.set("GET /popular/youtube", () => ({
    ...result("youtube", 0),
    state: "error",
    error_code: "cooldown",
    message: "後で再試行",
  }));
  s.state.handlers.set("GET /popular/lastfm", () => ({
    ...result("lastfm", 0),
    state: "error",
    error_code: "daily_budget",
    message: "本日の上限",
  }));
  s.view("discovery-panel");
  initDiscovery();
  await until(() =>
    document.querySelector("[data-provider=youtube] .error-msg"),
  );
  assert.equal(s.count("GET", "/popular/youtube"), 2);
  document.getElementById("discovery-tab-lastfm").click();
  await until(() =>
    document.querySelector("[data-provider=lastfm] .error-msg"),
  );
  assert.equal(s.count("GET", "/popular/lastfm"), 1);
});
