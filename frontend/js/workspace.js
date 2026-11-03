import { api } from "./api.js";

const call = (method, path, body) => api.workspace(method, path, body);
const labels = {
  ready: "持ち出し可能",
  server_saved: "サーバー保存済み・端末未指定",
  downloading: "取得中",
  needs_attention: "取得に要対応",
  device_offline: "端末オフライン・未確認",
  not_shared: "端末との共有設定を確認",
  unknown: "端末への到達状況は未確認",
  verifying: "端末のファイルを確認中",
  transferring: "端末へ転送中",
  empty: "同期対象なし",
};
function el(tag, cls = "", text = "") {
  const value = document.createElement(tag);
  value.className = cls;
  value.textContent = text;
  return value;
}
function button(text, action, cls = "btn btn-ghost") {
  const value = el("button", cls, text);
  value.type = "button";
  value.addEventListener("click", action);
  return value;
}
function status(value, message, error = false) {
  value.textContent = message;
  value.classList.toggle("error-msg", error);
}
function options(select, values, empty, preserveMissing = false) {
  const current = select.value;
  select.replaceChildren();
  if (empty) select.add(option(empty, ""));
  for (const value of values) select.add(option(value.name, String(value.id)));
  if (
    preserveMissing &&
    current &&
    ![...select.options].some((o) => o.value === current)
  )
    select.add(option("設定済み: " + current, current));
  if ([...select.options].some((o) => o.value === current))
    select.value = current;
}
const option = (label, value) => new document.defaultView.Option(label, value);
const bytes = (value) =>
  value ? `${(value / 1024 / 1024).toFixed(1)} MB` : "未確定";

export function initWorkspace() {
  let profiles = [],
    intakePlan = null,
    applying = null,
    refreshing = false,
    intakeVersion = 0,
    profileVersion = 0;
  const add = document.getElementById("sync-add-panel");
  const legacy = el("details", "legacy-add");
  legacy.append(el("summary", "", "アカウントから選ぶ・個別に追加"));
  for (const child of [...add.children])
    if (child.tagName !== "SUMMARY") legacy.append(child);
  const intake = el("section", "intake-box");
  intake.innerHTML = `<h2>まとめて追加</h2><p class="muted-hint">動画・プレイリスト・チャンネルのURLをまとめて貼り付け。名前を入力すると接続中のアカウントから検索できます。</p><form id="workspace-intake"><label class="syncthing-field"><span>URL、またはアカウント内のプレイリスト名</span><textarea name="text" rows="3" required placeholder="YouTubeのURLを1行ずつ貼り付け"></textarea></label><div class="intake-controls"><label class="syncthing-field"><span>保存プロファイル</span><select name="profile_id" class="workspace-profile-select"><option value="">設定の既定値</option></select></label><button class="btn btn-primary" type="submit">内容を確認</button></div></form><div class="workspace-feedback" role="status" aria-live="polite"></div><div class="intake-preview"></div>`;
  add.append(intake, legacy);
  const form = intake.querySelector("form"),
    intakeStatus = intake.querySelector("[role=status]"),
    preview = intake.querySelector(".intake-preview");
  const profileSelect = form.elements.namedItem("profile_id");
  try {
    profileSelect.dataset.selected =
      window.localStorage.getItem("intake-profile") || "";
  } catch {}
  profileSelect.addEventListener("change", () => {
    try {
      window.localStorage.setItem("intake-profile", profileSelect.value);
    } catch {}
    intakeVersion++;
    intakePlan = null;
    preview.replaceChildren();
  });
  form.elements.namedItem("text").addEventListener("input", () => {
    intakeVersion++;
    intakePlan = null;
    preview.replaceChildren();
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = form.querySelector("[type=submit]");
    if (submit.disabled) return;
    const version = ++intakeVersion;
    submit.disabled = true;
    preview.replaceChildren();
    intakePlan = null;
    status(intakeStatus, "種類・重複・取得可否を確認中…");
    try {
      const result = await call("POST", "/intake/preview", {
        text: form.elements.namedItem("text").value,
        profile_id: profileSelect.value ? Number(profileSelect.value) : null,
      });
      if (version !== intakeVersion) {
        status(intakeStatus, "入力が変わりました。内容を再確認してください。");
        return;
      }
      intakePlan = result;
      renderIntake(result);
      status(
        intakeStatus,
        result.items.length
          ? "追加する対象を確認してください。" +
              (result.truncated
                ? "先頭20件を表示しています。名前を絞り込めます。"
                : "")
          : "一致するプレイリストがありません。",
      );
    } catch (error) {
      status(intakeStatus, error.message, true);
    } finally {
      submit.disabled = false;
    }
  });
  function renderIntake(plan) {
    preview.replaceChildren();
    const list = el("div", "intake-items");
    plan.items.forEach((item, index) => {
      const row = el("label", "intake-item");
      const check = el("input");
      check.type = "checkbox";
      check.value = String(index);
      check.checked = item.state === "available";
      check.disabled = item.state !== "available";
      const content = el("span", "intake-item-info");
      content.append(
        el("strong", "", item.title),
        el(
          "small",
          "",
          item.state === "registered"
            ? "登録済み"
            : item.state === "duplicate"
              ? "同じURLが含まれています"
              : item.state === "unavailable"
                ? item.error
                : `${item.kind === "sync" ? "プレイリスト同期" : item.url_type === "channel" ? "チャンネル" : "動画"} · ${item.count ?? "—"}件 · ${plan.profile.name}`,
        ),
      );
      row.append(check, content);
      list.append(row);
    });
    const confirm = button(
      "選択した対象を追加",
      async () => {
        if (!intakePlan || confirm.disabled) return;
        const indices = [...list.querySelectorAll("input:checked")].map(
          (input) => Number(input.value),
        );
        if (!indices.length) return;
        list
          .querySelectorAll("input")
          .forEach((input) => (input.disabled = true));
        confirm.disabled = true;
        form.querySelector("[type=submit]").disabled = true;
        form.elements.namedItem("text").disabled = true;
        profileSelect.disabled = true;
        status(intakeStatus, "追加しています…");
        try {
          const result = await call("POST", "/intake/commit", {
            token: plan.token,
            indices,
          });
          const results = Object.values(result.results);
          const created = results.filter(
            (row) => row.state === "created" && !row.error,
          ).length;
          const errors = results.filter((row) => row.error).length;
          const retryable = results.filter(
            (row) => row.error && row.retryable !== false,
          ).length;
          status(
            intakeStatus,
            `${created}件を追加しました。${errors ? `${errors}件を完了できませんでした。` : ""}`,
            Boolean(errors),
          );
          let outcomes = preview.querySelector(".intake-outcomes");
          if (!outcomes) {
            outcomes = el("div", "intake-outcomes");
            preview.append(outcomes);
          }
          outcomes.replaceChildren(
            ...results.map((row) =>
              el(
                "div",
                row.error ? "error-msg" : "",
                `${row.title}: ${row.error || (row.state === "registered" ? "登録済み" : row.state === "created" ? "追加済み" : row.state)}`,
              ),
            ),
          );
          if (retryable) {
            confirm.textContent = "失敗した追加を再試行";
            confirm.disabled = false;
          } else if (errors) {
            confirm.textContent = "内容の再確認が必要";
            confirm.disabled = true;
            intakePlan = null;
          } else {
            confirm.textContent = "追加済み";
            list
              .querySelectorAll("input")
              .forEach((input) => (input.disabled = true));
            intakePlan = null;
          }
          if (
            Object.entries(result.results).some(
              ([index, row]) =>
                row.state === "created" &&
                plan.items[Number(index)]?.kind === "url",
            )
          ) {
            document.dispatchEvent(
              new document.defaultView.CustomEvent("url-sources-updated"),
            );
            const link = el("a", "text-button", "ダウンロード画面で確認");
            link.href = "#downloads";
            outcomes.append(link);
          }
          document.getElementById("yt-refresh-syncs-btn").click();
        } catch (error) {
          status(intakeStatus, error.message, true);
          confirm.disabled = false;
          confirm.textContent = "追加を再試行";
        } finally {
          form.querySelector("[type=submit]").disabled = false;
          form.elements.namedItem("text").disabled = false;
          profileSelect.disabled = false;
        }
      },
      "btn btn-primary",
    );
    const update = () => {
      confirm.disabled = !list.querySelector("input:checked:not(:disabled)");
    };
    list.addEventListener("change", update);
    update();
    preview.append(list, confirm);
    preview.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
  }

  const issueSection = el("details", "workspace-issues");
  issueSection.hidden = true;
  const issueSummary = el("summary", "", "要対応");
  issueSection.append(issueSummary);
  const attention = document.querySelector(".attention-stat");
  attention.setAttribute("role", "button");
  attention.tabIndex = 0;
  attention.setAttribute("aria-label", "要対応の内容を開く");
  const openIssues = () => {
    if (!issueSection.hidden) {
      issueSection.open = true;
      issueSection.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
    }
  };
  attention.addEventListener("click", openIssues);
  attention.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openIssues();
    }
  });
  const issueList = el("div", "issue-list"),
    issueStatus = el("div", "workspace-feedback");
  issueStatus.setAttribute("role", "status");
  issueSection.append(issueList, issueStatus);
  document.querySelector(".sync-overview").after(issueSection);
  const issueRows = new Map();
  async function refreshIssues() {
    try {
      const groups = await call("GET", "/issues");
      if (!Array.isArray(groups)) return;
      if (issueStatus.classList.contains("error-msg")) status(issueStatus, "");
      issueSection.hidden = !groups.length && !issueStatus.textContent;
      const active = groups.filter((group) => group.category !== "excluded"),
        excluded = groups.find((group) => group.category === "excluded");
      issueSummary.textContent = active.length
        ? `要対応 ${active.reduce((sum, group) => sum + group.count, 0)}件 · ${active.length === 1 ? active[0].title : active.length + "種類の原因"}`
        : excluded
          ? `取得から除外中 ${excluded.count}件`
          : "操作結果";
      if (
        groups.some((group) => group.category === "auth") &&
        !issueRows.has("auth")
      )
        issueSection.open = true;
      const keep = new Set();
      for (const group of groups) {
        keep.add(group.category);
        let row = issueRows.get(group.category);
        if (!row) {
          row = el("article", "issue-row");
          row.dataset.category = group.category;
          row.innerHTML =
            '<div class="issue-heading"><strong></strong><span></span></div><p class="muted-hint"></p><details><summary>対象と詳細</summary><div class="issue-members"></div></details><div class="issue-actions"></div>';
          const actions = row.querySelector(".issue-actions");
          if (group.category === "auth") {
            const link = el("a", "btn btn-primary", "YouTubeへ再接続");
            link.href = "#settings";
            actions.append(link);
          }
          if (group.category !== "excluded")
            actions.append(
              button(
                group.category === "auth"
                  ? "接続後にまとめて再試行"
                  : "まとめて再試行",
                (event) =>
                  actIssue(event.currentTarget, group.category, "retry"),
              ),
            );
          if (group.can_skip)
            actions.append(
              button("今後の取得から除外", (event) =>
                actIssue(event.currentTarget, group.category, "skip"),
              ),
            );
          issueRows.set(group.category, row);
          issueList.append(row);
        }
        row.querySelector("strong").textContent = group.title;
        row.querySelector(".issue-heading span").textContent =
          `${group.count}件`;
        row.querySelector("p").textContent = group.description;
        const signature = JSON.stringify(group.items);
        if (row.dataset.members !== signature) {
          row.dataset.members = signature;
          row.querySelector(".issue-members").replaceChildren(
            ...group.items.slice(0, 100).map((item) => {
              const line = el("div", "excluded-row");
              line.append(
                el("span", "", `${item.title}：${item.message || ""}`),
              );
              if (group.can_restore)
                line.append(
                  button("除外を解除", async (event) => {
                    const control = event.currentTarget;
                    control.disabled = true;
                    try {
                      await call(
                        "POST",
                        item.kind === "job"
                          ? `/jobs/${item.id}/restore`
                          : `/syncs/${item.sync_id}/tracks/${item.id}/restore`,
                      );
                      status(issueStatus, "除外を解除しました。");
                      await refreshIssues();
                    } catch (error) {
                      status(issueStatus, error.message, true);
                      control.disabled = false;
                    }
                  }),
                );
              return line;
            }),
          );
        }
      }
      for (const [key, row] of issueRows)
        if (!keep.has(key)) {
          row.remove();
          issueRows.delete(key);
        }
    } catch (error) {
      status(issueStatus, "要対応の取得に失敗しました: " + error.message, true);
      issueSection.hidden = false;
    }
  }
  async function actIssue(control, category, action) {
    control.disabled = true;
    status(
      issueStatus,
      action === "skip" ? "対象を除外しています…" : "再試行を依頼しています…",
    );
    try {
      const result = await call("POST", `/issues/${category}/${action}`);
      status(
        issueStatus,
        action === "skip"
          ? `${result.skipped}件を除外しました。同期の履歴から戻せます。`
          : `${result.queued}件をキューに追加しました。${result.waiting ? `${result.waiting}件は実行中です。` : ""}${result.errors?.length ? `${result.errors.length}件は再試行できませんでした。` : ""}`,
      );
      await refreshIssues();
      document.getElementById("yt-refresh-syncs-btn").click();
    } catch (error) {
      status(issueStatus, error.message, true);
    } finally {
      control.disabled = false;
    }
  }

  const profileSection = el("section", "settings-block profile-settings");
  profileSection.innerHTML = `<h2>保存プロファイル</h2><p class="muted-hint">用途ごとに形式・品質・保存先端末をひとまとめにします。編集しても既存の同期には自動適用しません。</p><div class="profile-list"></div><details class="profile-editor"><summary>作成・編集</summary><form><label class="syncthing-field"><span>名前</span><input name="name" required maxlength="80" placeholder="通勤用"></label><div class="preference-fields"><label class="syncthing-field"><span>保存形式</span><select name="audio_format"><option value="mp3">MP3</option><option value="m4a">M4A</option><option value="flac">FLAC</option><option value="aac">AAC</option><option value="ogg">OGG</option><option value="mp4">MP4</option><option value="webm">WEBM</option></select></label><label class="syncthing-field"><span>品質</span><select name="audio_quality"><option value="192">192 kbps</option><option value="320">320 kbps</option><option value="best">最高品質</option></select></label></div><label class="syncthing-field"><span>Syncthingの共有フォルダ</span><select name="target_folder_id"><option value="">フォルダを指定しない</option></select></label><label class="syncthing-field"><span>到達を確認する端末</span><select name="target_device_id"><option value="">端末を指定しない</option></select></label><label class="syncthing-field"><span>共有フォルダの範囲</span><select name="target_scope"><option value="downloads">ダウンロード全体</option><option value="playlist">このプレイリストのフォルダ自体</option></select></label><p class="muted-hint">Syncthingで実際に共有している範囲に合わせます。端末への到達はファイル単位で確認し、確認できない場合は完了と表示しません。</p><div class="profile-actions"><button type="submit" class="btn btn-primary">プロファイルを保存</button><button type="button" class="btn btn-ghost profile-new">新規に切替</button></div></form></details><div class="workspace-feedback" role="status" aria-live="polite"></div><div class="profile-apply"></div><label class="syncthing-field retention-setting"><span>同期元から消えた曲の保留日数</span><input type="number" min="1" max="90" value="7"></label><button type="button" class="btn btn-ghost retention-save">保留日数を保存</button><p class="muted-hint">日数を短くすると、すでに保留中の曲にも適用します。</p>`;
  document.querySelector(".download-preferences-block").after(profileSection);
  const profileForm = profileSection.querySelector("form"),
    profileStatus = profileSection.querySelector("[role=status]"),
    profileList = profileSection.querySelector(".profile-list");
  let editing = null;
  const field = (name) => profileForm.elements.namedItem(name);
  const profileFields = [
    "name",
    "audio_format",
    "audio_quality",
    "target_folder_id",
    "target_device_id",
    "target_scope",
  ];
  function fillProfile(value) {
    for (const name of profileFields) field(name).value = value[name] ?? "";
    const editor = profileSection.querySelector(".profile-editor");
    editor.open = true;
    editor.scrollIntoView?.({ behavior: "smooth", block: "start" });
    field("name").focus({ preventScroll: true });
    quality();
  }
  function quality() {
    field("audio_quality").disabled = ["mp4", "webm"].includes(
      field("audio_format").value,
    );
  }
  field("audio_format").addEventListener("change", quality);
  profileSection.querySelector(".profile-new").addEventListener("click", () => {
    editing = null;
    status(profileStatus, "新しい名前で保存できます。");
  });
  async function destinations() {
    try {
      const [folders, devices] = await Promise.all([
        api.syncthingListFolders(),
        api.syncthingListDevices(),
      ]);
      if (!Array.isArray(folders) || !Array.isArray(devices)) return;
      options(
        field("target_folder_id"),
        folders.map((f) => ({ id: f.id, name: f.label || f.id })),
        "フォルダを指定しない",
        true,
      );
      options(
        field("target_device_id"),
        devices.map((d) => ({ id: d.device_id, name: d.name || d.device_id })),
        "端末を指定しない",
        true,
      );
    } catch (error) {
      status(
        profileStatus,
        "端末一覧を取得できません。形式・品質のみでも保存できます。設定済みの端末情報は保持します。",
        true,
      );
    }
  }
  profileForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = profileForm.querySelector("[type=submit]");
    if (submit.disabled) return;
    submit.disabled = true;
    const values = Object.fromEntries(
      profileFields.map((name) => [name, field(name).value || null]),
    );
    try {
      const saved = await call(
        editing ? "PUT" : "POST",
        editing ? `/profiles/${editing}` : "/profiles",
        values,
      );
      editing = saved.id;
      status(profileStatus, "保存しました。既存の同期は変更していません。");
      await loadProfiles();
    } catch (error) {
      status(profileStatus, error.message, true);
    } finally {
      submit.disabled = false;
    }
  });
  async function loadProfiles() {
    try {
      const version = ++profileVersion;
      const result = await call("GET", "/profiles");
      if (version !== profileVersion) return;
      profiles = result;
      if (!Array.isArray(profiles)) throw Error("プロファイルを取得できません");
      options(profileSelect, profiles, "設定の既定値");
      if (profileSelect.dataset.selected) {
        profileSelect.value = profileSelect.dataset.selected;
        delete profileSelect.dataset.selected;
      }
      profileList.replaceChildren();
      for (const value of profiles) {
        const row = el("div", "profile-row"),
          info = el("div");
        info.append(
          el("strong", "", value.name),
          el(
            "small",
            "",
            `${value.audio_format.toUpperCase()} · ${value.audio_quality === "best" ? "最高品質" : value.audio_quality + " kbps"}${value.target_device_id ? " · 端末を指定済み" : ""}`,
          ),
        );
        const actions = el("div", "profile-actions");
        actions.append(
          button(value.builtin ? "コピーして編集" : "編集", () => {
            editing = value.builtin ? null : value.id;
            for (const name of ["target_folder_id", "target_device_id"])
              if (
                value[name] &&
                ![...field(name).options].some((o) => o.value === value[name])
              )
                field(name).add(
                  option("設定済み: " + value[name], value[name]),
                );
            fillProfile(
              value.builtin
                ? { ...value, name: value.name + "（コピー）" }
                : value,
            );
          }),
          button("既存同期へ適用", () => previewProfile(value)),
        );
        if (!value.builtin)
          actions.append(
            button("削除", async (event) => {
              const control = event.currentTarget;
              control.disabled = true;
              try {
                await call("DELETE", `/profiles/${value.id}`);
                status(
                  profileStatus,
                  "プロファイルを削除しました。既存の同期の設定は保持しています。",
                );
                await loadProfiles();
              } catch (error) {
                status(profileStatus, error.message, true);
                control.disabled = false;
              }
            }),
          );
        row.append(info, actions);
        profileList.append(row);
      }
    } catch (error) {
      status(profileStatus, error.message, true);
    }
  }
  async function previewProfile(value) {
    const host = profileSection.querySelector(".profile-apply");
    host.replaceChildren(el("h3", "", `「${value.name}」の適用対象`));
    applying = null;
    try {
      const syncs = await api.youtubeListSyncs();
      if (!syncs.length) {
        host.append(el("p", "muted-hint", "登録済みの同期はありません。"));
        return;
      }
      const list = el("div", "profile-targets");
      for (const sync of syncs) {
        const label = el("label", "intake-item"),
          input = el("input");
        input.type = "checkbox";
        input.value = String(sync.id);
        label.append(
          input,
          el(
            "span",
            "",
            `${sync.playlist_name} · ${sync.audio_format.toUpperCase()}`,
          ),
        );
        list.append(label);
      }
      const result = el("div", "profile-apply-result");
      const check = button("変更内容と再取得量を確認", async () => {
        const ids = [...list.querySelectorAll("input:checked")].map((input) =>
          Number(input.value),
        );
        if (!ids.length) {
          result.textContent = "適用する同期を選択してください。";
          return;
        }
        check.disabled = true;
        result.replaceChildren();
        applying = null;
        try {
          applying = await call("POST", `/profiles/${value.id}/preview`, {
            sync_ids: ids,
          });
          result.append(
            el(
              "p",
              "",
              `${applying.sync_count}件の同期を変更します。再取得: ${applying.redownload_count}曲、現在のファイル量 ${bytes(applying.existing_bytes)}（取得量の目安）。旧形式のファイルも保持するため、追加の空き容量が必要です。`,
            ),
          );
          const confirm = button(
            "この内容で適用・再取得",
            async () => {
              if (!applying) return;
              confirm.disabled = true;
              list
                .querySelectorAll("input")
                .forEach((input) => (input.disabled = true));
              check.disabled = true;
              try {
                const response = await call("POST", "/profiles/apply", {
                  token: applying.token,
                });
                status(
                  profileStatus,
                  `${response.applied}件に適用しました。${response.queued}曲を再取得します。${response.dispatch_errors?.length ? "キュー登録に失敗した曲は「要対応」から再試行してください。" : ""}`,
                );
                result.replaceChildren();
                applying = null;
                document.getElementById("yt-refresh-syncs-btn").click();
                await refreshIssues();
              } catch (error) {
                status(profileStatus, error.message, true);
                confirm.disabled = false;
              } finally {
                list
                  .querySelectorAll("input")
                  .forEach((input) => (input.disabled = false));
                check.disabled = false;
              }
            },
            "btn btn-primary",
          );
          result.append(confirm);
        } catch (error) {
          result.textContent = error.message;
        } finally {
          check.disabled = false;
        }
      });
      list.addEventListener("change", () => {
        applying = null;
        result.replaceChildren();
      });
      host.append(list, check, result);
      host.scrollIntoView?.({ behavior: "smooth", block: "start" });
    } catch (error) {
      host.append(el("p", "error-msg", error.message));
    }
  }
  profileSection
    .querySelector(".retention-save")
    .addEventListener("click", async (event) => {
      const control = event.currentTarget;
      control.disabled = true;
      try {
        await api.updateSettings({
          removed_track_retention_days: Number(
            profileSection.querySelector(".retention-setting input").value,
          ),
        });
        status(profileStatus, "保留日数を保存しました。");
      } catch (error) {
        status(profileStatus, error.message, true);
      } finally {
        control.disabled = false;
      }
    });

  const historyStates = new WeakMap();
  function decorateCards() {
    for (const card of document.querySelectorAll(".yt-sync-card")) {
      const previous = card.querySelector(".delivery-state");
      if (previous) {
        if (
          previous.dataset.device !== card.dataset.targetDevice ||
          card.dataset.serverComplete === "false"
        ) {
          previous.textContent =
            card.dataset.serverComplete === "false"
              ? "取得状況を確認中"
              : labels.unknown;
          previous.classList.remove("is-ready");
        }
        previous.dataset.device = card.dataset.targetDevice;
        continue;
      }
      const profileLabel = el("span", "sync-profile-label");
      card.querySelector(".yt-sync-caption").append(profileLabel);
      const deliveryLabel = el("span", "delivery-state");
      deliveryLabel.dataset.device = card.dataset.targetDevice;
      deliveryLabel.setAttribute("role", "status");
      card.querySelector(".yt-sync-caption").append(deliveryLabel);
      const panel = card.querySelector(".sync-detail-panel"),
        history = el("details", "sync-history");
      history.append(
        el("summary", "", "変更履歴・保留中の曲"),
        el("div", "history-content"),
      );
      history.addEventListener("toggle", () => {
        if (history.open) refreshHistory(card, history);
      });
      panel.append(history);
    }
  }
  async function refreshHistory(card, host) {
    let state = historyStates.get(host);
    if (!state) {
      state = { busy: false, signature: null, offset: 0 };
      historyStates.set(host, state);
    }
    if (state.busy) return;
    state.busy = true;
    const content = host.querySelector(".history-content");
    try {
      const result = await call(
        "GET",
        `/syncs/${card.dataset.syncId}/history${state.offset ? "?retained_offset=" + state.offset : ""}`,
      );
      content.querySelector(".history-error")?.remove();
      const signature = JSON.stringify(result);
      if (state.signature === signature) return;
      state.signature = signature;
      content.replaceChildren(
        el(
          "p",
          "muted-hint",
          `同期元から消えた曲は${result.retention_days}日間保留します。復元した曲は、同期元から消えていても保持します。`,
        ),
      );
      for (const item of result.retained) {
        const row = el("div", "retained-row"),
          info = el("div");
        info.append(
          el("strong", "", item.title),
          el(
            "small",
            "",
            item.excluded || item.status === "skipped"
              ? "取得から除外中"
              : item.status === "complete"
                ? "復元して保持中"
                : item.file_retained
                  ? `ファイルを保留中 · ${item.expires_at ? new Date(item.expires_at).toLocaleDateString("ja-JP") + "まで" : ""}`
                  : "ファイルの保留期限切れ・復元時に再取得",
          ),
        );
        row.append(info);
        if (item.status === "complete")
          row.append(
            button("保持を解除", async (event) => {
              const control = event.currentTarget;
              control.disabled = true;
              try {
                await call(
                  "POST",
                  `/syncs/${card.dataset.syncId}/tracks/${item.id}/release`,
                );
                state.signature = null;
                state.busy = false;
                await refreshHistory(card, host);
              } catch (error) {
                content.append(el("p", "error-msg", error.message));
                control.disabled = false;
              }
            }),
          );
        else
          row.append(
            button(
              item.excluded || item.status === "skipped"
                ? "除外を解除・復元"
                : "復元して保持",
              async (event) => {
                const control = event.currentTarget;
                control.disabled = true;
                try {
                  await call(
                    "POST",
                    `/syncs/${card.dataset.syncId}/tracks/${item.id}/restore`,
                  );
                  state.signature = null;
                  state.busy = false;
                  await refreshHistory(card, host);
                  document.getElementById("yt-refresh-syncs-btn").click();
                } catch (error) {
                  content.append(el("p", "error-msg", error.message));
                  control.disabled = false;
                }
              },
            ),
          );
        content.append(row);
      }
      if (result.retained_total > 200 || state.offset) {
        const pager = el("div", "profile-actions");
        pager.append(
          el(
            "span",
            "muted-hint",
            `保留・除外・保持 ${result.retained_total}件`,
          ),
        );
        if (state.offset)
          pager.append(
            button("前の200件", () => {
              if (state.busy) return;
              state.offset = Math.max(0, state.offset - 200);
              state.signature = null;
              refreshHistory(card, host);
            }),
          );
        if (result.has_more)
          pager.append(
            button("次の200件", () => {
              if (state.busy) return;
              state.offset += 200;
              state.signature = null;
              refreshHistory(card, host);
            }),
          );
        content.append(pager);
      }
      for (const event of result.events) {
        const details = event.details;
        const line =
          event.kind === "sync"
            ? `追加 ${details.added_count ?? details.added?.length ?? 0}曲 · 保留 ${details.removed_count ?? details.removed?.length ?? 0}曲`
            : event.kind === "profile"
              ? `プロファイル「${details.name}」を適用`
              : event.kind === "skip"
                ? "取得から除外"
                : event.kind === "release"
                  ? "保持を解除"
                  : event.kind === "fetch_failed"
                    ? "一覧の取得に失敗"
                    : event.kind === "download_failed"
                      ? "曲の取得に失敗"
                      : event.kind === "download_recovered"
                        ? "再取得に成功"
                        : "復元して保持";
        const row = el("details", "history-event");
        row.append(
          el(
            "summary",
            "",
            `${new Date(event.created_at).toLocaleString("ja-JP")} · ${line}`,
          ),
        );
        if (details.error) row.append(el("p", "", details.error));
        for (const item of [
          ...(details.added || []),
          ...(details.removed || []),
          ...(details.tracks || []),
        ])
          row.append(el("p", "", item.title));
        content.append(row);
      }
      if (!result.events.length && !result.retained.length)
        content.append(el("p", "muted-hint", "まだ変更履歴はありません。"));
    } catch (error) {
      let notice = content.querySelector(".history-error");
      if (!notice) {
        notice = el("p", "error-msg history-error");
        content.append(notice);
      }
      notice.textContent = error.message;
    } finally {
      state.busy = false;
    }
  }
  async function refreshDelivery() {
    decorateCards();
    await Promise.all(
      [...document.querySelectorAll(".yt-sync-card")].map(async (card) => {
        const output = card.querySelector(".delivery-state");
        card.querySelector(".sync-profile-label").textContent =
          card.dataset.profileName || "";
        const history = card.querySelector(".sync-history");
        if (history.open) await refreshHistory(card, history);
        try {
          const result = await call(
            "GET",
            `/syncs/${card.dataset.syncId}/delivery`,
          );
          output.textContent = `${result.device_name ? result.device_name + " · " : ""}${labels[result.state] || labels.unknown}${result.total && card.dataset.targetDevice ? ` · ${result.verified}/${result.total}曲確認済み` : ""}`;
          output.classList.toggle("is-ready", result.state === "ready");
          output.title = result.checked_at
            ? `最終確認: ${new Date(result.checked_at * 1000).toLocaleString("ja-JP")}（最大30秒の確認キャッシュ）`
            : "";
        } catch {
          output.textContent = labels.unknown;
          output.classList.remove("is-ready");
        }
      }),
    );
  }
  async function refresh() {
    if (
      refreshing ||
      document.hidden ||
      !document.getElementById("playlists-panel").classList.contains("active")
    )
      return;
    refreshing = true;
    try {
      await Promise.all([refreshIssues(), refreshDelivery()]);
    } finally {
      refreshing = false;
    }
  }
  document.addEventListener("sync-list-updated", () => {
    decorateCards();
    refresh();
  });
  document.addEventListener("visibilitychange", refresh);
  document.addEventListener("workspace-navigation", refresh);
  window.addEventListener("hashchange", refresh);
  const observer = new window.MutationObserver(decorateCards);
  observer.observe(document.getElementById("yt-sync-list"), {
    childList: true,
  });
  const timer = window.setInterval(refresh, 5000);
  window.addEventListener(
    "pagehide",
    () => {
      window.clearInterval(timer);
      observer.disconnect();
    },
    { once: true },
  );
  loadProfiles();
  destinations();
  api
    .getSettings()
    .then((values) => {
      profileSection.querySelector(".retention-setting input").value =
        values.removed_track_retention_days ?? 7;
    })
    .catch(() => {});
  decorateCards();
  refresh();
}
