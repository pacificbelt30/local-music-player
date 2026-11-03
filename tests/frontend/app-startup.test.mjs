import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { JSDOM } from "jsdom";
import { api } from "../../frontend/js/api.js";
const tick = () => new Promise((r) => setImmediate(r));
async function until(fn) {
  for (let i = 0; i < 100; i++) {
    if (fn()) return;
    await tick();
  }
  assert.ok(fn());
}

test("the real app starts only visible work and initializes each visited screen once", async (t) => {
  const dom = new JSDOM(
    await readFile(
      new URL("../../frontend/index.html", import.meta.url),
      "utf8",
    ),
    { url: "http://localhost/#sync", pretendToBeVisual: true },
  );
  const keys = [
    "window",
    "document",
    "location",
    "history",
    "localStorage",
    "Audio",
    "EventSource",
    "CustomEvent",
  ];
  const old = Object.fromEntries(
    keys.map((k) => [k, Object.getOwnPropertyDescriptor(globalThis, k)]),
  );
  for (const key of [
    "window",
    "document",
    "location",
    "history",
    "localStorage",
    "CustomEvent",
  ])
    Object.defineProperty(globalThis, key, {
      value: dom.window[key],
      configurable: true,
    });
  Object.defineProperty(globalThis, "Audio", {
    value: class extends EventTarget {},
    configurable: true,
  });
  let streams = 0;
  Object.defineProperty(globalThis, "EventSource", {
    value: class {
      constructor() {
        streams++;
      }
      close() {}
    },
    configurable: true,
  });
  dom.window.setInterval = () => 1;
  dom.window.clearInterval = () => {};
  const original = { ...api },
    calls = [];
  const stub = (name, result) => {
    api[name] = async (...args) => {
      calls.push({ name, args });
      return typeof result === "function"
        ? result(...args)
        : structuredClone(result);
    };
  };
  const reads = (name) => calls.filter((c) => c.name === name).length;
  stub("getSettings", {
    default_audio_format: "m4a",
    default_audio_quality: "192",
    account_playlist_method: "url",
    removed_track_retention_days: 7,
  });
  stub("youtubeListSyncs", [
    {
      id: 1,
      playlist_id: "PL1",
      playlist_name: "One",
      audio_format: "m4a",
      audio_quality: "192",
      enabled: true,
      track_count: 0,
      downloaded_count: 0,
    },
  ]);
  stub("youtubeAuthStatus", { authenticated: true });
  stub("youtubeListAccountPlaylists", [
    {
      playlist_id: "PLown",
      title: "My playlist",
      item_count: 2,
      privacy_status: "public",
    },
  ]);
  stub("workspace", (method, path) =>
    path === "/profiles"
      ? [
          {
            id: -1,
            name: "スマホ用",
            audio_format: "m4a",
            audio_quality: "192",
          },
        ]
      : path.endsWith("/delivery")
        ? { state: "empty", total: 0, verified: 0 }
        : [],
  );
  stub("listTracks", [{ id: 1, title: "Saved", download_url: "#" }]);
  stub("listUrls", []);
  stub("listQueue", []);
  stub("syncthingListFolders", []);
  stub("syncthingListDevices", []);
  stub("syncthingStatus", { available: false });
  t.after(() => {
    Object.assign(api, original);
    dom.window.close();
    for (const key of keys) {
      if (old[key]) Object.defineProperty(globalThis, key, old[key]);
      else delete globalThis[key];
    }
  });
  await import("../../frontend/js/app.js");
  await until(() => document.querySelector(".yt-sync-card"));
  for (const name of [
    "getSettings",
    "youtubeAuthStatus",
    "youtubeListAccountPlaylists",
    "listTracks",
    "listUrls",
    "listQueue",
    "syncthingListFolders",
    "syncthingListDevices",
    "syncthingStatus",
  ])
    assert.equal(reads(name), 0, name + " must be deferred");
  assert.equal(
    calls.filter((c) => c.name === "workspace" && c.args[1] === "/profiles")
      .length,
    0,
  );
  assert.equal(streams, 0);
  assert.equal(
    calls.filter((c) => c.name === "workspace" && c.args[1] === "/issues")
      .length,
    1,
  );
  document.querySelector("#open-sync-add").click();
  await until(
    () =>
      document.querySelector(".workspace-profile-select").options.length > 1,
  );
  assert.equal(reads("youtubeListAccountPlaylists"), 0);
  assert.equal(reads("getSettings"), 0);
  assert.equal(reads("syncthingListFolders"), 0);
  document.querySelector("#sync-add-panel > .legacy-add").open = true;
  await until(() => document.querySelector(".yt-pl-item"));
  assert.equal(reads("youtubeListAccountPlaylists"), 1);
  assert.equal(reads("getSettings"), 1);
  const navigate = (panel) =>
    document.querySelector(`[data-panel="${panel}"]`).click();
  navigate("right-panel");
  await until(() => document.querySelector(".track-item"));
  assert.equal(reads("listTracks"), 1);
  assert.equal(reads("listQueue"), 0);
  navigate("playlists-panel");
  navigate("right-panel");
  await tick();
  assert.equal(reads("listTracks"), 1);
  navigate("left-panel");
  await until(() => reads("listQueue") === 1);
  assert.equal(reads("listUrls"), 1);
  assert.equal(streams, 1);
  navigate("playlists-panel");
  navigate("left-panel");
  await tick();
  assert.equal(reads("listQueue"), 1);
  assert.equal(streams, 1);
  navigate("settings-panel");
  await until(() => reads("syncthingListDevices") === 1);
  await tick();
  assert.equal(reads("getSettings"), 2);
  assert.equal(reads("syncthingListFolders"), 1);
  assert.equal(reads("syncthingStatus"), 1);
  navigate("playlists-panel");
  navigate("settings-panel");
  await tick();
  assert.equal(reads("getSettings"), 2);
  assert.equal(reads("syncthingListDevices"), 1);
});
