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
      ffmpeg_threads: Number(form.ffmpeg_threads.value || 1),
      celery_worker_concurrency: Number(form.celery_worker_concurrency.value || 0),
      discord_webhook_url: form.discord_webhook_url.value || "",
      notify_on_download_complete: form.notify_on_download_complete.checked,
      notify_on_download_failed: form.notify_on_download_failed.checked,
      notify_on_db_error: form.notify_on_db_error.checked,
      notify_on_youtube_auth_expired: form.notify_on_youtube_auth_expired.checked,
    };

    try {
      await api.updateSettings(payload);
      ok.textContent = "保存しました";
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
  form.ffmpeg_threads.value = String(s.ffmpeg_threads ?? 1);
  form.celery_worker_concurrency.value = String(s.celery_worker_concurrency ?? 0);
  form.discord_webhook_url.value = s.discord_webhook_url ?? "";
  form.notify_on_download_complete.checked = s.notify_on_download_complete ?? false;
  form.notify_on_download_failed.checked = s.notify_on_download_failed ?? true;
  form.notify_on_db_error.checked = s.notify_on_db_error ?? true;
  form.notify_on_youtube_auth_expired.checked = s.notify_on_youtube_auth_expired ?? true;
}
