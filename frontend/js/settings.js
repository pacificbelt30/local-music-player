import { api } from "./api.js";

export function initSettings() {
  const modal = document.getElementById("settings-modal");
  const openBtn = document.getElementById("settings-badge");
  const closeEls = modal.querySelectorAll("[data-close-settings-modal]");
  const form = document.getElementById("settings-form");
  const updateForm = document.getElementById("ytdlp-update-form");
  let polling;

  async function refreshUpdateStatus(loadConfig = false) {
    try {
      const state = await api.ytdlpStatus();
      const labels = {idle: "待機中", checking: "新版を確認中", installing: "候補版を導入中", testing: "動作検証中", updated: "更新完了", up_to_date: "最新版を使用中", needs_configuration: "検証用URLの設定待ち", rejected: "候補版の検証失敗・現行版を維持", inconclusive: "両版の検証失敗・現行版を維持", failed: "更新失敗・現行版を維持", interrupted: "更新中断・現行版を維持", rolled_back: "切り戻し完了・自動更新は停止中"};
      const checked = state.last_checked_at ? new Date(state.last_checked_at).toLocaleString() : "未確認";
      document.getElementById("ytdlp-status").textContent = `使用版: ${state.active.version} / ${labels[state.status] || state.status} / 最終確認: ${checked}`;
      document.getElementById("ytdlp-error").textContent = state.error || "";
      document.getElementById("ytdlp-results").textContent = state.tests ? Object.entries(state.tests).map(([name, result]) => `${name === "current" ? "現行版" : "候補版"} ${result.version}: ${result.passed ? "成功" : "失敗"}\n${(result.checks || [result.error]).join("\n")}`).join("\n\n") : "";
      document.getElementById("ytdlp-check").disabled = state.busy;
      document.getElementById("ytdlp-rollback").disabled = state.busy || !state.previous;
      updateForm.querySelector('button[type="submit"]').disabled = state.busy;
      if (loadConfig) {
        updateForm.enabled.checked = state.config.enabled;
        if (!Array.from(updateForm.interval_minutes.options).some(option => Number(option.value) === state.config.interval_minutes)) {
          updateForm.interval_minutes.add(new Option(`${state.config.interval_minutes}分`, String(state.config.interval_minutes)));
        }
        updateForm.interval_minutes.value = String(state.config.interval_minutes);
        for (const key of ["video_url", "playlist_url", "channel_url"]) updateForm[key].value = state.config[key];
      }
    } catch (error) {
      document.getElementById("ytdlp-error").textContent = error.message;
    }
  }

  openBtn?.addEventListener("click", async () => {
    modal.classList.remove("hidden");
    await loadSettings();
    await refreshUpdateStatus(true);
    clearInterval(polling);
    polling = setInterval(() => {
      if (modal.classList.contains("hidden")) clearInterval(polling);
      else refreshUpdateStatus();
    }, 5000);
  });
  closeEls.forEach((el) => el.addEventListener("click", () => modal.classList.add("hidden")));

  updateForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api.ytdlpConfigure({enabled: updateForm.enabled.checked, interval_minutes: Number(updateForm.interval_minutes.value), video_url: updateForm.video_url.value, playlist_url: updateForm.playlist_url.value, channel_url: updateForm.channel_url.value});
      await refreshUpdateStatus(true);
    } catch (error) { document.getElementById("ytdlp-error").textContent = error.message; }
  });
  document.getElementById("ytdlp-check").addEventListener("click", async () => {
    try {
      await api.ytdlpCheck();
      document.getElementById("ytdlp-status").textContent = "更新確認をキューに追加しました";
    } catch (error) { document.getElementById("ytdlp-error").textContent = error.message; }
  });
  document.getElementById("ytdlp-rollback").addEventListener("click", async () => {
    try { await api.ytdlpRollback(); await refreshUpdateStatus(true); }
    catch (error) { document.getElementById("ytdlp-error").textContent = error.message; }
  });

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
      silence_trim_start_secs: Number(form.silence_trim_start_secs.value || 0),
      silence_trim_end_secs: Number(form.silence_trim_end_secs.value || 0),
      ffmpeg_threads: Number(form.ffmpeg_threads.value || 1),
      ffmpeg_memory_limit_mb: Number(form.ffmpeg_memory_limit_mb.value || 0),
      celery_worker_concurrency: Number(form.celery_worker_concurrency.value || 0),
      discord_webhook_url: form.discord_webhook_url.value || "",
      notify_on_download_complete: form.notify_on_download_complete.checked,
      notify_on_download_failed: form.notify_on_download_failed.checked,
      notify_on_db_error: form.notify_on_db_error.checked,
      notify_on_youtube_auth_expired: form.notify_on_youtube_auth_expired.checked,
      notify_on_oauth_expiry_warning: form.notify_on_oauth_expiry_warning.checked,
      oauth_expiry_warning_minutes: Number(form.oauth_expiry_warning_minutes.value || 60),
    };

    try {
      const result = await api.updateSettings(payload);
      if (result.silence_trim_requeued) {
        ok.textContent = "保存しました（無音トリミングの秒数を増やしたため、既存トラックの再ダウンロードをキューに追加しました）";
      } else if (result.silence_trim_retrimmed_locally) {
        ok.textContent = "保存しました（無音トリミングの秒数を減らしたため、既存トラックに直接トリミングを再適用しました）";
      } else {
        ok.textContent = "保存しました";
      }
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
  form.silence_trim_start_secs.value = String(s.silence_trim_start_secs ?? 2.5);
  form.silence_trim_end_secs.value = String(s.silence_trim_end_secs ?? 2.5);
  form.ffmpeg_threads.value = String(s.ffmpeg_threads ?? 1);
  form.ffmpeg_memory_limit_mb.value = String(s.ffmpeg_memory_limit_mb ?? 0);
  form.celery_worker_concurrency.value = String(s.celery_worker_concurrency ?? 0);
  form.discord_webhook_url.value = s.discord_webhook_url ?? "";
  form.notify_on_download_complete.checked = s.notify_on_download_complete ?? false;
  form.notify_on_download_failed.checked = s.notify_on_download_failed ?? true;
  form.notify_on_db_error.checked = s.notify_on_db_error ?? true;
  form.notify_on_youtube_auth_expired.checked = s.notify_on_youtube_auth_expired ?? true;
  form.notify_on_oauth_expiry_warning.checked = s.notify_on_oauth_expiry_warning ?? true;
  form.oauth_expiry_warning_minutes.value = String(s.oauth_expiry_warning_minutes ?? 60);
}
