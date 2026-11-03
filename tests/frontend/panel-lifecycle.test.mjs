import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";
import { whenPanelVisible } from "../../frontend/js/panel-lifecycle.js";
test("panels start once on first visible visit and wait while the document is hidden", (t) => {
  const dom = new JSDOM(
    '<section id="sync" class="active"></section><section id="files"></section>',
    { pretendToBeVisual: true },
  );
  const previous = {
    document: Object.getOwnPropertyDescriptor(globalThis, "document"),
    window: Object.getOwnPropertyDescriptor(globalThis, "window"),
  };
  for (const key of ["document", "window"])
    Object.defineProperty(globalThis, key, {
      value: dom.window[key],
      configurable: true,
    });
  t.after(() => {
    dom.window.close();
    for (const key of ["document", "window"])
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
  });
  let reads = 0;
  whenPanelVisible("files", () => reads++);
  assert.equal(reads, 0);
  document.getElementById("files").classList.add("active");
  Object.defineProperty(document, "hidden", {
    value: true,
    configurable: true,
  });
  document.dispatchEvent(new window.Event("workspace-navigation"));
  assert.equal(reads, 0);
  Object.defineProperty(document, "hidden", {
    value: false,
    configurable: true,
  });
  document.dispatchEvent(new window.Event("visibilitychange"));
  assert.equal(reads, 1);
  document.dispatchEvent(new window.Event("workspace-navigation"));
  window.dispatchEvent(new window.Event("pageshow"));
  assert.equal(reads, 1);
  let immediate = 0;
  whenPanelVisible("sync", () => immediate++);
  assert.equal(immediate, 1);
});
