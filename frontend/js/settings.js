import { api } from "./api.js";

export function initSettings() {
  const modal = document.getElementById("settings-modal");
  const openBtn = document.getElementById("settings-badge");
  const closeEls = modal.querySelectorAll("[data-close-settings-modal]");
  const form = document.getElementById("settings-form");

  openBtn?.addEventListener("click", async () => {
    modal.classList.remove("hidden");
    await loadSettings();
  });
  closeEls.forEach((el) => el.addEventListener("click", () => modal.classList.add("hidden")));

  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = document.getElementById("settings-error");
    const ok = document.getElementById("settings-ok");
    err.textContent = "";
    ok.textContent = "";

    const payload = {
      url_sync_interval_minutes: Number(form.url_sync_interval_minutes.value),
      youtube_sync_interval_minutes: Number(form.youtube_sync_interval_minutes.value),
      download_gain_percent: Number(form.download_gain_percent.value || 0),
    };

    try {
      const saved = await api.updateSettings(payload);
      ok.textContent = "保存しました";
      syncInlineSelectors(saved);
    } catch (e2) {
      err.textContent = e2.message;
    }
  });
}

async function loadSettings() {
  const form = document.getElementById("settings-form");
  const s = await api.getSettings();
  form.url_sync_interval_minutes.value = String(s.url_sync_interval_minutes);
  form.youtube_sync_interval_minutes.value = String(s.youtube_sync_interval_minutes);
  form.download_gain_percent.value = String(s.download_gain_percent ?? 0);
}

function syncInlineSelectors(s) {
  const urlSelect = document.getElementById("url-sync-interval");
  const ytSelect = document.getElementById("youtube-sync-interval");
  if (urlSelect) urlSelect.value = String(s.url_sync_interval_minutes);
  if (ytSelect) ytSelect.value = String(s.youtube_sync_interval_minutes);
}
