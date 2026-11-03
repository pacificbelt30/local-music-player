import { whenPanelVisible } from "./panel-lifecycle.js";
import { initNavigation } from "./navigation.js";
import { initQueue } from "./queue.js";
import { initLibrary } from "./library.js";
import { initPlaylists } from "./playlists.js";
import { initSyncthing } from "./syncthing.js";
import { initSettings } from "./settings.js";
import { initWorkspace } from "./workspace.js";
import { initDebug } from "./debug.js";
import { badgePresentation } from "./syncthing-status.js";

let syncthingBadgeUpdating = false;
initNavigation();
initWorkspace();
initPlaylists();
whenPanelVisible("left-panel", initQueue);
whenPanelVisible("right-panel", initLibrary);
whenPanelVisible("settings-panel", () => {
  initSettings();
  initSyncthing();
  initDebug();
  updateSyncthingBadge();
});

async function updateSyncthingBadge() {
  if (syncthingBadgeUpdating) return;
  syncthingBadgeUpdating = true;
  const badge = document.getElementById("syncthing-badge");
  try {
    const { api } = await import("./api.js");
    const status = await api.syncthingStatus();
    const view = badgePresentation(status);
    badge.querySelector("span").textContent = view.text;
    badge.title = view.title;
    badge.className = "settings-card " + view.className;
  } catch (error) {
    badge.querySelector("span").textContent = "接続状況を取得できません";
    badge.title = error.message;
    badge.className = "settings-card";
  } finally {
    syncthingBadgeUpdating = false;
  }
}
const refreshBadge = () => {
  if (
    !document.hidden &&
    document.getElementById("settings-panel").classList.contains("active")
  )
    updateSyncthingBadge();
};
window.addEventListener("syncthing-config-changed", refreshBadge);
document.addEventListener("visibilitychange", refreshBadge);
window.setInterval(refreshBadge, 30000);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js");
}
