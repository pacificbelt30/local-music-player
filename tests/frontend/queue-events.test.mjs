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
const job = (id, status = "downloading") => ({
  id,
  title: `job ${id}`,
  status,
  progress_pct: 0,
});
async function setup(t) {
  const dom = new JSDOM(
    await readFile(
      new URL("../../frontend/index.html", import.meta.url),
      "utf8",
    ),
    { url: "http://localhost/", pretendToBeVisual: true },
  );
  const keys = ["window", "document", "EventSource"];
  const old = Object.fromEntries(
    keys.map((key) => [key, Object.getOwnPropertyDescriptor(globalThis, key)]),
  );
  let stream;
  const streams = [];
  for (const key of ["window", "document"])
    Object.defineProperty(globalThis, key, {
      value: dom.window[key],
      configurable: true,
    });
  Object.defineProperty(globalThis, "EventSource", {
    value: class {
      constructor() {
        stream = this;
        this.closed = false;
        streams.push(this);
      }
      close() {
        this.closed = true;
      }
    },
    configurable: true,
  });
  const original = {
    listUrls: api.listUrls,
    listQueue: api.listQueue,
    cancelJob: api.cancelJob,
    retryJob: api.retryJob,
    deleteUrl: api.deleteUrl,
  };
  api.listUrls = async () => [];
  let records = [job(1)],
    reads = 0,
    read = async () => records;
  api.listQueue = () => {
    reads++;
    return read();
  };
  t.after(() => {
    Object.assign(api, original);
    dom.window.close();
    for (const key of keys) {
      if (old[key]) Object.defineProperty(globalThis, key, old[key]);
      else delete globalThis[key];
    }
  });
  const { initQueue } = await import(
    `../../frontend/js/queue.js?events=${t.name}`
  );
  initQueue();
  await until(() => document.querySelector(".job-item"));
  return {
    send: (events) => stream.onmessage({ data: JSON.stringify(events) }),
    setRecords: (value) => (records = value),
    setRead: (fn) => (read = fn),
    reads: () => reads,
    streams,
    stream: () => stream,
  };
}

test("completed job disappears when the active snapshot becomes empty", async (t) => {
  const q = await setup(t);
  q.setRecords([]);
  q.send([]);
  await until(() => !document.querySelector(".job-item"));
  assert.equal(q.reads(), 2);
  q.send([]);
  await tick();
  assert.equal(q.reads(), 2);
});

test("failed job gets retry controls after it leaves active snapshot", async (t) => {
  const q = await setup(t);
  q.setRecords([job(1, "failed")]);
  q.send([]);
  await until(() => document.querySelector(".retry-job:not([hidden])"));
  assert.equal(document.querySelector(".status-badge").textContent, "失敗");
  q.send([]);
  await tick();
  assert.equal(q.reads(), 2);
});

test("progress updates do not fetch the list; new jobs trigger one fetch at a time", async (t) => {
  const q = await setup(t);
  q.send([{ job_id: 1, status: "downloading", progress_pct: 65 }]);
  assert.equal(document.querySelector(".progress-fill").style.width, "65%");
  assert.equal(q.reads(), 1);
  let finish;
  q.setRead(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const snapshot = [
    { job_id: 1, status: "downloading", progress_pct: 66 },
    { job_id: 2, status: "pending", progress_pct: 0 },
  ];
  q.send(snapshot);
  q.send(snapshot);
  assert.equal(q.reads(), 2);
  finish([job(1), job(2, "pending")]);
  await until(() => document.querySelectorAll(".job-item").length === 2);
  q.send(snapshot);
  assert.equal(q.reads(), 2);
});

test("snapshot reconciliation retries after a failed list request", async (t) => {
  const q = await setup(t);
  q.setRead(async () => {
    throw new Error("offline");
  });
  q.send([]);
  await tick();
  assert.ok(document.querySelector(".job-item"));
  q.setRead(async () => []);
  q.send([]);
  await until(() => !document.querySelector(".job-item"));
  assert.equal(q.reads(), 3);
});

test("unified intake refreshes the URL list and queue in the download workspace", async (t) => {
  const q = await setup(t);
  api.listUrls = async () => [
    {
      id: 2,
      title: "Added through intake",
      url: "https://youtu.be/new",
      url_type: "video",
      audio_format: "m4a",
      audio_quality: "192",
      sync_enabled: true,
    },
  ];
  document.dispatchEvent(
    new document.defaultView.CustomEvent("url-sources-updated"),
  );
  await until(
    () =>
      document.querySelector(".url-item-title")?.textContent ===
      "Added through intake",
  );
  assert.equal(q.reads(), 2);
});

test("retry failures keep the row and explain the error without permitting duplicate requests", async (t) => {
  const q = await setup(t);
  q.setRecords([job(1, "failed"), job(2)]);
  q.send([]);
  await until(() => document.querySelectorAll(".job-item").length === 2);
  const row = document.querySelector('[data-job-id="1"]'),
    other = document.querySelector('[data-job-id="2"]');
  let reject,
    calls = 0;
  api.retryJob = () => {
    calls++;
    return new Promise((_, fail) => (reject = fail));
  };
  const button = row.querySelector(".retry-job");
  button.click();
  button.click();
  assert.equal(calls, 1);
  assert.equal(button.disabled, true);
  assert.equal(row.querySelector(".cancel-job").disabled, true);
  reject(new Error("offline <script>bad</script>"));
  await until(() => !button.disabled);
  assert.equal(document.querySelector('[data-job-id="1"]'), row);
  assert.equal(document.querySelector('[data-job-id="2"]'), other);
  assert.match(
    row.querySelector(".row-action-feedback").textContent,
    /再試行に失敗.*offline/,
  );
  assert.equal(row.querySelector("script"), null);
  api.retryJob = async () => {
    q.setRecords([job(1, "pending"), job(2)]);
    return job(1, "pending");
  };
  button.click();
  await until(() => !button.disabled);
  assert.equal(document.querySelector('[data-job-id="2"]'), other);
  assert.equal(row.querySelector(".retry-job").hidden, true);
  assert.equal(row.querySelector(".row-action-feedback").textContent, "");
});

test("cancel failures are visible and a later successful cancel preserves other focused rows", async (t) => {
  const q = await setup(t);
  q.setRecords([job(1), job(2)]);
  document.dispatchEvent(
    new document.defaultView.CustomEvent("url-sources-updated"),
  );
  await until(() => document.querySelectorAll(".job-item").length === 2);
  const row = document.querySelector('[data-job-id="1"]'),
    other = document.querySelector('[data-job-id="2"]');
  api.cancelJob = async () => {
    throw new Error("permission denied");
  };
  row.querySelector(".cancel-job").click();
  await until(() => !row.hasAttribute("aria-busy"));
  assert.match(row.textContent, /取消に失敗.*permission denied/);
  const focus = other.querySelector(".cancel-job");
  focus.focus();
  api.cancelJob = async () => {
    q.setRecords([job(2)]);
  };
  row.querySelector(".cancel-job").click();
  await until(() => !row.isConnected);
  await tick();
  assert.equal(document.querySelector(".job-item"), other);
  assert.equal(document.activeElement, focus);
});

test("background tabs close progress connections and resume once with a fresh list", async (t) => {
  const q = await setup(t);
  const first = q.stream();
  Object.defineProperty(document, "hidden", {
    value: true,
    configurable: true,
  });
  document.dispatchEvent(new document.defaultView.Event("visibilitychange"));
  assert.equal(first.closed, true);
  first.onerror();
  assert.equal(
    document.querySelector("#queue-connection-status").textContent,
    "",
  );
  Object.defineProperty(document, "hidden", {
    value: false,
    configurable: true,
  });
  document.dispatchEvent(new document.defaultView.Event("visibilitychange"));
  document.dispatchEvent(new document.defaultView.Event("visibilitychange"));
  assert.equal(q.streams.length, 2);
  assert.notEqual(q.stream(), first);
  await until(() => q.reads() === 2);
  q.stream().onerror();
  assert.match(
    document.querySelector("#queue-connection-status").textContent,
    /再接続中/,
  );
  q.stream().onopen();
  await until(() => q.reads() === 3);
  assert.equal(
    document.querySelector("#queue-connection-status").textContent,
    "",
  );
  window.dispatchEvent(new window.Event("pagehide"));
  assert.equal(q.stream().closed, true);
  window.dispatchEvent(new window.Event("pageshow"));
  assert.equal(q.streams.length, 3);
});

test("queue refresh errors retain rows and offer a retry", async (t) => {
  const q = await setup(t),
    row = document.querySelector(".job-item");
  q.setRead(async () => {
    throw new Error("offline");
  });
  q.send([]);
  await until(() => document.querySelector("#queue-status button"));
  assert.equal(document.querySelector(".job-item"), row);
  q.setRead(async () => []);
  document.querySelector("#queue-status button").click();
  await until(() => !document.querySelector(".job-item"));
  assert.equal(document.querySelector("#queue-status").textContent, "");
});

test("URL list ignores older results and registration failures remain actionable", async (t) => {
  await setup(t);
  const pending = [];
  api.listUrls = () => new Promise((resolve) => pending.push(resolve));
  const refresh = () =>
    document.dispatchEvent(
      new document.defaultView.CustomEvent("url-sources-updated"),
    );
  refresh();
  refresh();
  const source = {
    id: 5,
    title: "Newest",
    url_type: "video",
    audio_format: "m4a",
    audio_quality: "192",
  };
  pending[1]([source]);
  await until(() => document.querySelector(".url-item"));
  pending[0]([]);
  await tick();
  const row = document.querySelector(".url-item");
  assert.equal(row.querySelector(".url-item-title").textContent, "Newest");
  let calls = 0,
    fail;
  api.deleteUrl = () => {
    calls++;
    return new Promise((_, reject) => (fail = reject));
  };
  row.querySelector(".delete-url").click();
  row.querySelector(".delete-url").click();
  assert.equal(calls, 1);
  fail(new Error("offline"));
  await until(() => !row.querySelector(".delete-url").disabled);
  assert.match(row.textContent, /登録解除に失敗.*offline/);
  assert.equal(document.querySelector(".url-item"), row);
});

test("initial stream connection does not reload an already loaded queue", async (t) => {
  const q = await setup(t);
  q.stream().onopen();
  await tick();
  assert.equal(q.reads(), 1);
  q.stream().onerror();
  q.stream().onopen();
  await until(() => q.reads() === 2);
});
