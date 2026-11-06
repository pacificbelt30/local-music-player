import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { JSDOM } from "jsdom";
import { api } from "../../frontend/js/api.js";
import { initWorkspace } from "../../frontend/js/workspace.js";
const html = await readFile(
  new URL("../../frontend/index.html", import.meta.url),
  "utf8",
);
const tick = () => new Promise((resolve) => setImmediate(resolve));
async function until(fn) {
  for (let i = 0; i < 100; i++) {
    if (fn()) return;
    await tick();
  }
  assert.ok(fn());
}
const profile = (id = 1) => ({
  id,
  name: "Phone",
  audio_format: "m4a",
  audio_quality: "192",
  target_scope: "downloads",
  target_device_id: null,
  target_folder_id: null,
});
function card(doc) {
  const value = doc.createElement("div");
  value.className = "yt-sync-card";
  value.dataset.syncId = "1";
  value.dataset.targetDevice = "phone";
  value.innerHTML =
    '<div class="yt-sync-caption"></div><section class="sync-detail-panel"></section>';
  doc.getElementById("yt-sync-list").replaceChildren(value);
  return value;
}
async function setup(t, options = {}) {
  const dom = new JSDOM(html, { url: "http://localhost/" });
  const keys = ["window", "document"];
  const old = Object.fromEntries(
    keys.map((k) => [k, Object.getOwnPropertyDescriptor(globalThis, k)]),
  );
  for (const key of keys)
    Object.defineProperty(globalThis, key, {
      value: dom.window[key],
      configurable: true,
    });
  Object.defineProperty(document, "hidden", {
    value: false,
    configurable: true,
  });
  let poll;
  dom.window.setInterval = (fn) => {
    poll = fn;
    return 1;
  };
  dom.window.clearInterval = () => {};
  const original = { ...api };
  const state = {
    calls: [],
    profiles: [profile()],
    handlers: new Map(),
    issues: options.issues || [],
    refreshes: 0,
  };
  api.workspace = async (method, path, body) => {
    state.calls.push({ method, path, body });
    const handler = state.handlers.get(method + " " + path);
    if (handler) return handler(body);
    if (path === "/profiles") return state.profiles;
    if (path === "/issues") return state.issues;
    if (path.endsWith("/delivery"))
      return { state: "ready", total: 2, verified: 2 };
    if (path.endsWith("/history"))
      return { events: [], retained: [], retention_days: 7 };
    if (path === "/intake/preview")
      return {
        token: "a".repeat(32),
        profile: profile(),
        items: [
          { title: "Shared <img>", kind: "sync", count: 2, state: "available" },
          { title: "Existing", state: "registered" },
        ],
      };
    if (path === "/intake/commit")
      return {
        complete: true,
        results: { 0: { state: "created", title: "Shared" } },
      };
    return {};
  };
  api.syncthingListFolders = async () => [{ id: "folder", label: "Downloads" }];
  api.syncthingListDevices = async () => [
    { device_id: "phone", name: "Phone" },
  ];
  api.getSettings = async () => ({ removed_track_retention_days: 7 });
  api.updateSettings = async (values) => values;
  api.youtubeListSyncs = async () => [
    { id: 1, playlist_name: "Existing", audio_format: "mp3" },
  ];
  document
    .getElementById("yt-refresh-syncs-btn")
    .addEventListener("click", () => state.refreshes++);
  const row = card(document);
  initWorkspace();
  document.querySelector("#sync-add-panel").open = true;
  await until(() => document.querySelector(".profile-row"));
  t.after(() => {
    Object.assign(api, original);
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
    row,
    poll: () => poll(),
    count: (method, path) =>
      state.calls.filter((c) => c.method === method && c.path === path).length,
  };
}

test("one intake accepts mixed inputs, previews safely and commits only selected available entries", async (t) => {
  const s = await setup(t);
  const form = document.querySelector("#workspace-intake");
  form.elements.text.value = "https://youtube.com/playlist?list=shared";
  form.dispatchEvent(new s.dom.window.Event("submit", { cancelable: true }));
  await until(() => document.querySelector(".intake-item"));
  assert.match(document.querySelector(".intake-item").textContent, /<img>/);
  assert.equal(document.querySelector(".intake-item img"), null);
  assert.equal(
    document.querySelectorAll(".intake-item input:disabled").length,
    1,
  );
  document.querySelector(".intake-preview > .btn").click();
  await until(
    () =>
      document.querySelector(".intake-preview > .btn").textContent ===
      "追加済み",
  );
  assert.deepEqual(
    s.state.calls.find((c) => c.path === "/intake/commit").body.indices,
    [0],
  );
  assert.equal(s.state.refreshes, 1);
});

test("a Last.fm source opens a video preview and still requires explicit queue confirmation", async (t) => {
  const s = await setup(t);
  s.state.handlers.set("POST /intake/preview", () => ({
    token: "a".repeat(32),
    profile: profile(),
    items: [
      { title: "Selected video", kind: "url", state: "available", count: 1 },
    ],
  }));
  const detail = {
    url: "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    title: "Song <img>",
    artist: "Artist",
    accepted: false,
  };
  document.dispatchEvent(
    new s.dom.window.CustomEvent("workspace-import-video", { detail }),
  );
  await until(() => document.querySelector(".intake-item"));
  assert.equal(detail.accepted, true);
  assert.equal(
    document.querySelector("#workspace-intake").elements.text.value,
    detail.url,
  );
  assert.equal(document.querySelector("#sync-add-panel").open, true);
  assert.equal(document.querySelector(".discovery-intake-context img"), null);
  assert.match(
    document.querySelector(".discovery-intake-context").textContent,
    /Song <img>.*Artist/,
  );
  assert.equal(s.count("POST", "/intake/commit"), 0);
  document.querySelector(".intake-preview > .btn").click();
  await until(() => s.count("POST", "/intake/commit") === 1);
  await until(
    () => !document.querySelector("#workspace-intake [type=submit]").disabled,
  );
  window.confirm = () => {
    throw Error("Completed input is not an unsaved draft");
  };
  const next = {
    url: "https://www.youtube.com/watch?v=abcdefghijk",
    title: "Next",
    artist: "Artist",
    accepted: false,
  };
  document.dispatchEvent(
    new s.dom.window.CustomEvent("workspace-import-video", { detail: next }),
  );
  assert.equal(next.accepted, true);
  assert.equal(
    document.querySelector("#workspace-intake").elements.text.value,
    next.url,
  );
  assert.equal(s.count("POST", "/intake/commit"), 1);
});

test("source handoff cannot overwrite an existing draft without the user's decision", async (t) => {
  const s = await setup(t);
  const form = document.querySelector("#workspace-intake");
  form.elements.text.value = "my existing draft";
  window.confirm = () => false;
  const detail = {
    url: "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    accepted: false,
  };
  document.dispatchEvent(
    new s.dom.window.CustomEvent("workspace-import-video", { detail }),
  );
  assert.equal(form.elements.text.value, "my existing draft");
  assert.equal(detail.accepted, false);
  assert.equal(s.count("POST", "/intake/preview"), 0);
});

test("editing input while its preview is pending discards stale preview", async (t) => {
  const s = await setup(t);
  let finish;
  s.state.handlers.set(
    "POST /intake/preview",
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const form = document.querySelector("#workspace-intake");
  form.elements.text.value = "old";
  form.dispatchEvent(new s.dom.window.Event("submit", { cancelable: true }));
  await until(() => typeof finish === "function");
  form.elements.text.value = "new";
  form.elements.text.dispatchEvent(new s.dom.window.Event("input"));
  finish({
    token: "x",
    items: [{ state: "available", title: "old" }],
    profile: profile(),
  });
  await tick();
  assert.equal(document.querySelector(".intake-item"), null);
  assert.match(
    document.querySelector(".intake-box [role=status]").textContent,
    /入力が変わりました/,
  );
});

test("intake dispatch failure can retry the same plan without changing selected targets", async (t) => {
  const s = await setup(t);
  let attempts = 0;
  s.state.handlers.set("POST /intake/commit", () => {
    attempts++;
    return {
      results: {
        0: {
          state: "created",
          title: "One",
          ...(attempts === 1 ? { error: "retry" } : {}),
        },
      },
    };
  });
  const form = document.querySelector("#workspace-intake");
  form.elements.text.value = "url";
  form.dispatchEvent(new s.dom.window.Event("submit", { cancelable: true }));
  await until(() => document.querySelector(".intake-item"));
  const confirm = document.querySelector(".intake-preview > .btn");
  confirm.click();
  await until(() => confirm.textContent === "失敗した追加を再試行");
  assert.equal(document.querySelector(".intake-item input").disabled, true);
  confirm.click();
  await until(() => confirm.textContent === "追加済み");
  assert.equal(attempts, 2);
});

test("one grouped outage exposes reconnect and reports bulk retry failure without hiding the issue", async (t) => {
  const group = {
    category: "auth",
    title: "Reconnect",
    description: "Reconnect first",
    count: 20,
    items: [{ title: "One", message: "invalid_grant" }],
  };
  const s = await setup(t, { issues: [group] });
  await until(() => document.querySelector(".issue-row"));
  assert.equal(document.querySelectorAll(".issue-row").length, 1);
  assert.equal(document.querySelector(".issue-actions a").hash, "#settings");
  s.state.handlers.set("POST /issues/auth/retry", () => {
    throw Error("offline");
  });
  document.querySelector(".issue-actions button").click();
  await tick();
  assert.ok(document.querySelector(".issue-row"));
  assert.match(
    document.querySelector(".workspace-issues [role=status]").textContent,
    /offline/,
  );
});

test("delivery labels become unknown after a failure and never keep a ready badge", async (t) => {
  const s = await setup(t);
  await until(() =>
    document
      .querySelector(".delivery-state")
      .textContent.includes("持ち出し可能"),
  );
  s.state.handlers.set("GET /syncs/1/delivery", () => {
    throw Error("offline");
  });
  await s.poll();
  assert.match(document.querySelector(".delivery-state").textContent, /未確認/);
  assert.equal(
    document.querySelector(".delivery-state").classList.contains("is-ready"),
    false,
  );
});

test("history restores a retained track without leaving the drawer and keeps error text safe", async (t) => {
  const s = await setup(t);
  s.state.handlers.set("GET /syncs/1/history", () => ({
    events: [],
    retained: [
      {
        id: 2,
        title: "<script>Title</script>",
        status: "removed",
        file_retained: true,
      },
    ],
    retention_days: 7,
  }));
  const history = document.querySelector(".sync-history");
  history.open = true;
  history.dispatchEvent(new s.dom.window.Event("toggle"));
  await until(() => history.querySelector(".retained-row"));
  assert.equal(history.querySelector("script"), null);
  history.querySelector("button").click();
  await until(() => s.count("POST", "/syncs/1/tracks/2/restore") === 1);
  assert.equal(history.open, true);
  assert.equal(s.row.querySelector(".sync-history"), history);
});

test("existing profile application needs an explicit preview and confirmation", async (t) => {
  const s = await setup(t);
  s.state.handlers.set("POST /profiles/1/preview", () => ({
    token: "p",
    sync_count: 1,
    redownload_count: 3,
    existing_bytes: 1024,
  }));
  s.state.handlers.set("POST /profiles/apply", () => ({
    applied: 1,
    queued: 3,
  }));
  [...document.querySelectorAll(".profile-row button")]
    .find((b) => b.textContent === "既存同期へ適用")
    .click();
  await until(() => document.querySelector(".profile-targets input"));
  assert.equal(s.count("POST", "/profiles/apply"), 0);
  document.querySelector(".profile-targets input").click();
  [...document.querySelectorAll(".profile-apply button")]
    .find((b) => b.textContent === "変更内容と再取得量を確認")
    .click();
  await until(() => document.querySelector(".profile-apply-result button"));
  assert.match(
    document.querySelector(".profile-apply-result").textContent,
    /3曲/,
  );
  assert.equal(s.count("POST", "/profiles/apply"), 0);
  document.querySelector(".profile-apply-result button").click();
  await until(() => s.count("POST", "/profiles/apply") === 1);
});

test("saved profile remains in edit mode and destination options survive a missing device", async (t) => {
  const s = await setup(t);
  s.state.handlers.set("POST /profiles", (values) => ({ id: 9, ...values }));
  s.state.handlers.set("PUT /profiles/9", (values) => ({ id: 9, ...values }));
  const form = document.querySelector(".profile-editor form");
  assert.equal(
    form.elements.target_folder_id.options[0].textContent,
    "フォルダを指定しない",
  );
  assert.equal(
    form.elements.target_device_id.options[0].textContent,
    "端末を指定しない",
  );
  form.elements.name.value = "New";
  form.dispatchEvent(new s.dom.window.Event("submit", { cancelable: true }));
  await until(() => s.count("POST", "/profiles") === 1);
  await tick();
  form.elements.audio_quality.value = "320";
  form.dispatchEvent(new s.dom.window.Event("submit", { cancelable: true }));
  await until(() => s.count("PUT", "/profiles/9") === 1);
});

test("attention summary stays compact and the overview opens its recovery actions", async (t) => {
  const s = await setup(t, {
    issues: [
      {
        category: "network",
        title: "通信が一時的に失敗しています",
        count: 4,
        items: [],
      },
    ],
  });
  await until(() => document.querySelector(".issue-row"));
  const details = document.querySelector(".workspace-issues");
  assert.equal(details.open, false);
  assert.match(details.querySelector("summary").textContent, /4件/);
  document.querySelector(".attention-stat").click();
  assert.equal(details.open, true);
});

test("cards without a target still check whether server files exist", async (t) => {
  const s = await setup(t);
  s.row.dataset.targetDevice = "";
  s.row.dataset.serverComplete = "true";
  s.state.handlers.set("GET /syncs/1/delivery", () => ({
    state: "needs_attention",
    total: 2,
    verified: 0,
  }));
  await s.poll();
  assert.match(document.querySelector(".delivery-state").textContent, /要対応/);
  assert.equal(
    document.querySelector(".delivery-state").classList.contains("is-ready"),
    false,
  );
});

test("a video added through the unified entry updates downloads and links to them", async (t) => {
  const s = await setup(t);
  s.state.handlers.set("POST /intake/preview", () => ({
    token: "v".repeat(32),
    profile: profile(),
    items: [
      {
        kind: "url",
        url_type: "video",
        title: "Video",
        state: "available",
        count: 1,
      },
    ],
  }));
  let updated = 0;
  document.addEventListener("url-sources-updated", () => updated++);
  const form = document.querySelector("#workspace-intake");
  form.elements.text.value = "https://youtu.be/video";
  form.dispatchEvent(new s.dom.window.Event("submit", { cancelable: true }));
  await until(() => document.querySelector(".intake-item"));
  document.querySelector(".intake-preview > .btn").click();
  await until(() => document.querySelector(".intake-outcomes a"));
  assert.equal(updated, 1);
  assert.equal(document.querySelector(".intake-outcomes a").hash, "#downloads");
});
