import { api } from "./api.js";

const providers = ["youtube", "lastfm"];
const names = { youtube: "YouTube Data API", lastfm: "Last.fm" };
const countries = { JP: "日本", US: "米国", GB: "英国" };
const owners = new WeakMap();
const rowItems = new WeakMap();
async function call(method, path, body, signal) {
  const result = await api.discovery(method, path, body, signal);
  if (result?.error_code !== "cooldown") return result;
  // The provider's shared two-second guard can apply just after a connection
  // test or a first chart lookup. Keep the current action pending and retry once.
  await new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const abort = () => {
      window.clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timer = window.setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, 2100);
    signal?.addEventListener("abort", abort, { once: true });
  });
  return api.discovery(method, path, body, signal);
}
const el = (tag, className = "", text = "") => {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
};
function state() {
  if (!owners.has(document))
    owners.set(document, {
      config: null,
      pending: null,
      forms: new Map(),
      panels: new Map(),
      sequences: new Map(),
      controllers: new Map(),
      dirty: true,
      selected: null,
      selectionExplicit: false,
    });
  return owners.get(document);
}
function message(host, text = "", error = false, retry) {
  host.replaceChildren(document.createTextNode(text));
  host.classList.toggle("error-msg", error);
  if (retry) {
    const button = el("button", "btn btn-ghost", "再試行");
    button.type = "button";
    button.addEventListener("click", retry);
    host.append(button);
  }
}
async function config(reload = false) {
  const s = state();
  if (s.pending) return s.pending;
  if (s.config && !reload) return s.config;
  s.pending = call("GET", "/config")
    .then((value) => {
      if (
        !providers.every(
          (p) => value[p] && typeof value[p].enabled === "boolean",
        )
      )
        throw Error("連携設定を読み取れませんでした");
      s.config = value;
      return value;
    })
    .finally(() => {
      s.pending = null;
    });
  return s.pending;
}
function configured(value) {
  return Boolean(value?.enabled && value?.api_key_set);
}
function changed(provider, value) {
  const s = state();
  if (s.config) s.config[provider] = value;
  document.dispatchEvent(
    new document.defaultView.CustomEvent("discovery-config-changed", {
      detail: { provider },
    }),
  );
}

export function initDiscoverySettings() {
  const s = state(),
    container = document.getElementById("discovery-provider-settings");
  for (const provider of providers) {
    const form = document.createElement("form");
    form.className = "discovery-config-form";
    form.dataset.provider = provider;
    form.innerHTML =
      '<div class="discovery-provider-heading"><h3></h3><span class="discovery-key-state"></span></div><p class="muted-hint provider-description"></p><label class="discovery-enable"><input type="checkbox" name="enabled">この連携を有効にする</label><div class="preference-fields"><label class="syncthing-field"><span>APIキー</span><input type="password" name="api_key" maxlength="512" autocomplete="new-password" autocapitalize="off" spellcheck="false" placeholder="APIキーを入力"></label><label class="syncthing-field"><span>人気情報の地域</span><select name="region"><option value="JP">日本</option><option value="US">米国</option><option value="GB">英国</option></select></label></div><div class="discovery-config-actions"><button type="submit" class="btn btn-primary">保存</button><button type="button" class="btn btn-ghost discovery-test">接続確認</button><button type="button" class="btn btn-ghost discovery-clear">キーを削除</button><a class="text-button provider-key-link" target="_blank" rel="noopener noreferrer">キーの取得先 ↗</a></div><div class="discovery-feedback" role="status" aria-live="polite"></div>';
    form.querySelector("h3").textContent = names[provider];
    form.querySelector("h3").id = "discovery-config-" + provider;
    form.querySelector("h3").tabIndex = -1;
    const keyHint = el(
      "p",
      "muted-hint",
      "新しいキーは保存してから接続確認できます。空欄で保存すると現在のキーを保持します。",
    );
    form.querySelector(".preference-fields").after(keyHint);
    form.querySelector(".provider-description").textContent =
      provider === "youtube"
        ? "地域別の人気音楽動画を取得します。YouTube Data API v3を有効にしたAPIキーを指定してください。OAuthは不要です。"
        : "国別人気曲と類似曲を調べます。Last.fmのAPIキーを指定してください。利用者のLast.fmログインは不要です。";
    form.querySelector(".provider-key-link").href =
      provider === "youtube"
        ? "https://console.cloud.google.com/apis/credentials"
        : "https://www.last.fm/api/account/create";
    const feedback = form.querySelector("[role=status]");
    const entry = { form, feedback, busy: false, value: null };
    s.forms.set(provider, entry);
    const busy = (value) => {
      entry.busy = value;
      form.setAttribute("aria-busy", String(value));
      for (const control of form.querySelectorAll("input,select,button"))
        control.disabled = value;
      if (!value) {
        form.querySelector(".discovery-test").disabled =
          !entry.value?.api_key_set;
        form.querySelector(".discovery-clear").disabled =
          !entry.value?.api_key_set;
      }
    };
    entry.busyState = busy;
    entry.fill = (value) => {
      entry.value = value;
      form.elements.namedItem("enabled").checked = value.enabled;
      form.elements.namedItem("region").value = value.region;
      form.querySelector(".discovery-key-state").textContent = value.api_key_set
        ? "キー設定済み"
        : "キー未設定";
      form.elements.namedItem("api_key").placeholder = value.api_key_set
        ? "空欄なら保存済みのキーを保持"
        : "APIキーを入力";
    };
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (entry.busy) return;
      busy(true);
      message(feedback, "保存中…");
      try {
        const input = form.elements.namedItem("api_key");
        const payload = {
          enabled: form.elements.namedItem("enabled").checked,
          region: form.elements.namedItem("region").value,
        };
        if (input.value.trim()) payload.api_key = input.value.trim();
        const value = await call("PATCH", "/config/" + provider, payload);
        input.value = "";
        entry.fill(value);
        changed(provider, value);
        message(
          feedback,
          "保存しました。" +
            (value.enabled
              ? "「見つける」で利用できます。"
              : "連携は無効です。"),
        );
        if (configured(value)) {
          const link = el("a", "text-button", "見つけるで確認する");
          link.href = "#discover";
          link.dataset.navigate = "discovery-panel";
          link.dataset.focusTarget = "discovery-title";
          link.addEventListener("click", () => {
            s.selected = provider;
            s.selectionExplicit = true;
          });
          feedback.append(document.createTextNode(" "), link);
        }
      } catch (error) {
        message(feedback, "保存に失敗しました: " + error.message, true);
      } finally {
        busy(false);
      }
    });
    form
      .querySelector(".discovery-test")
      .addEventListener("click", async () => {
        if (entry.busy) return;
        busy(true);
        message(feedback, "保存済みのキーで確認中…");
        try {
          const result = await call("POST", "/config/" + provider + "/test");
          message(feedback, result.message, result.state !== "ready");
        } catch (error) {
          message(feedback, "確認に失敗しました: " + error.message, true);
        } finally {
          busy(false);
        }
      });
    form
      .querySelector(".discovery-clear")
      .addEventListener("click", async () => {
        if (
          entry.busy ||
          !window.confirm(
            names[provider] + "のAPIキーを削除し、連携を無効にしますか？",
          )
        )
          return;
        busy(true);
        message(feedback, "キーを削除中…");
        try {
          const value = await call("PATCH", "/config/" + provider, {
            clear_key: true,
          });
          form.elements.namedItem("api_key").value = "";
          entry.fill(value);
          changed(provider, value);
          message(feedback, "キーを削除し、連携を無効にしました。");
        } catch (error) {
          message(feedback, "削除に失敗しました: " + error.message, true);
        } finally {
          busy(false);
        }
      });
    busy(true);
    container.append(form);
  }
  async function load() {
    for (const entry of s.forms.values()) entry.busyState(true);
    const status = document.getElementById("discovery-settings-status");
    message(status, "連携設定を読み込み中…");
    try {
      const values = await config(true);
      for (const p of providers) {
        s.forms.get(p).fill(values[p]);
        s.forms.get(p).busyState(false);
      }
      message(status);
    } catch (error) {
      message(status, "設定を取得できません: " + error.message, true, load);
    }
  }
  load();
}

function safeLink(label, url) {
  const link = el("a", "text-button", label);
  try {
    const parsed = new URL(url);
    if (
      parsed.protocol !== "https:" ||
      !["www.youtube.com", "youtube.com", "www.last.fm", "last.fm"].includes(
        parsed.hostname,
      )
    )
      return el("span", "muted-hint", label);
    link.href = parsed.href;
  } catch {
    return el("span", "muted-hint", label);
  }
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}
function trackRow(item) {
  const row = el("li", "discovery-item");
  row.dataset.itemId = item.id;
  const info = el("div", "discovery-item-info");
  info.append(el("strong"), el("span", "discovery-artist"));
  row.append(info, el("div", "discovery-item-actions"));
  updateRow(row, item);
  return row;
}
function updateRow(row, item) {
  rowItems.set(row, item);
  const title = row.querySelector("strong"),
    artist = row.querySelector(".discovery-artist");
  if (title.textContent !== item.title) title.textContent = item.title;
  const description = `${item.artist_label || "アーティスト"} · ${item.artist || "不明"}`;
  if (artist.textContent !== description) artist.textContent = description;
  const actions = row.querySelector(".discovery-item-actions");
  const links = [
    safeLink(item.youtube_id ? "YouTubeで開く" : "曲情報", item.url),
  ];
  if (!item.youtube_id)
    links.push(
      safeLink(
        "YouTubeで探す",
        "https://www.youtube.com/results?search_query=" +
          encodeURIComponent(item.artist + " " + item.title),
      ),
    );
  links.forEach((link, i) => {
    const current = actions.children[i];
    if (current && current.tagName === link.tagName) {
      if (current.textContent !== link.textContent)
        current.textContent = link.textContent;
      if (link.tagName === "A") {
        current.href = link.href;
        current.target = link.target;
        current.rel = link.rel;
      }
    } else if (current) current.replaceWith(link);
    else actions.append(link);
  });
  // Keep an existing action focused when a refresh updates its track metadata.
  for (const child of [...actions.children].slice(links.length))
    if (
      !child.classList.contains("discovery-seed") &&
      !child.classList.contains("discovery-download")
    )
      child.remove();
  let seed = actions.querySelector(".discovery-seed");
  let download = actions.querySelector(".discovery-download");
  if (!item.youtube_id && item.artist?.trim()) {
    if (!seed) {
      seed = el("button", "text-button discovery-seed", "似た曲");
      seed.type = "button";
      actions.append(seed);
    }
    seed.setAttribute("aria-label", `「${item.title}」に似た曲を探す`);
    if (!download) {
      download = el("button", "text-button discovery-download", "DL・同期");
      download.type = "button";
      actions.append(download);
    }
    download.setAttribute("aria-label", `「${item.title}」の保存候補を確認`);
  } else {
    seed?.remove();
    download?.remove();
  }
}
function renderRows(host, items, limit = 20) {
  const existing = new Map(
    [...host.children].map((row) => [row.dataset.itemId, row]),
  );
  const rows = items
    .slice(0, limit)
    .map((item) =>
      existing.has(String(item.id))
        ? (updateRow(existing.get(String(item.id)), item),
          existing.get(String(item.id)))
        : trackRow(item),
    );
  const keep = new Set(rows);
  for (const child of [...host.children]) if (!keep.has(child)) child.remove();
  let cursor = host.firstElementChild;
  for (const row of rows) {
    if (row === cursor) cursor = cursor.nextElementSibling;
    else host.insertBefore(row, cursor);
  }
}
function cancel(s, name) {
  s.sequences.set(name, (s.sequences.get(name) || 0) + 1);
  s.controllers.get(name)?.abort();
}
function cancelSource(s) {
  cancel(s, "source");
  if (s.sourceRequest) {
    s.sourceRequest.button.disabled = false;
    message(s.sourceRequest.feedback);
    s.sourceRequest = null;
  }
}
function visible() {
  return (
    !state().away &&
    !document.hidden &&
    document.getElementById("discovery-panel").classList.contains("active")
  );
}

export function initDiscovery() {
  const s = state(),
    container = document.getElementById("discovery-popular"),
    overview = document.querySelector(".discovery-overview");
  for (const provider of providers) {
    const card = el("article", "discovery-source");
    card.dataset.provider = provider;
    card.id = "discovery-source-" + provider;
    card.setAttribute("role", "tabpanel");
    card.setAttribute("aria-labelledby", "discovery-tab-" + provider);
    card.hidden = true;
    const heading = el("div", "discovery-source-heading");
    heading.append(
      el(
        "h2",
        "",
        provider === "youtube" ? "人気の音楽動画" : "Last.fmで人気の曲",
      ),
    );
    const refresh = el("button", "btn btn-ghost", "更新");
    refresh.type = "button";
    heading.append(refresh);
    const description = el(
      "p",
      "muted-hint",
      provider === "youtube"
        ? "YouTubeの人気音楽動画です。週間の楽曲チャートとは集計が異なります。"
        : "Last.fm利用者の先週の聴取をもとにした国別ランキングです。",
    );
    const feedback = el("div", "discovery-feedback");
    feedback.setAttribute("role", "status");
    feedback.setAttribute("aria-live", "polite");
    const timestamp = el("p", "discovery-timestamp");
    const list = el("ol", "discovery-list");
    const more = el("button", "btn btn-ghost discovery-more", "もっと見る");
    more.type = "button";
    more.hidden = true;
    const entry = {
      card,
      refresh,
      feedback,
      timestamp,
      list,
      more,
      items: [],
      limit: 20,
      pending: false,
      loaded: false,
      expiresAt: Infinity,
    };
    s.panels.set(provider, entry);
    more.addEventListener("click", () => {
      entry.limit += 20;
      renderRows(list, entry.items, entry.limit);
      more.hidden = entry.limit >= entry.items.length;
    });
    refresh.addEventListener("click", () => loadProvider(provider, true));
    card.append(heading, description, feedback, timestamp, list, more);
    container.append(card);
  }
  const similarForm = document.getElementById("discovery-similar-form"),
    similarStatus = document.getElementById("discovery-similar-status"),
    similarResults = document.getElementById("discovery-similar-results");
  const similarButton = similarForm.querySelector("[type=submit]");
  let similarPending = false;
  const tabs = [
    ...document.querySelectorAll(".discovery-view-tabs [role=tab]"),
  ];
  function selectView(view, explicit = true, fetch = true) {
    if (![...providers, "similar"].includes(view)) return;
    if (s.selected !== view) cancelSource(s);
    s.selected = view;
    if (explicit) s.selectionExplicit = true;
    for (const tab of tabs) {
      const active = tab.dataset.discoveryView === view;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    }
    for (const [provider, entry] of s.panels) {
      entry.card.hidden = provider !== view;
      if (provider !== view && entry.pending) {
        cancel(s, provider);
        entry.pending = false;
        entry.card.removeAttribute("aria-busy");
      }
    }
    container.hidden = view === "similar";
    similarForm.closest(".discovery-similar").hidden = view !== "similar";
    if (view !== "similar" && similarPending) {
      cancel(s, "similar");
      similarPending = false;
      similarButton.disabled = !configured(s.config?.lastfm);
      message(similarStatus, "検索を中断しました。もう一度検索できます。");
    }
    const entry = s.panels.get(view);
    if (
      fetch &&
      s.config &&
      entry &&
      (!entry.loaded || entry.expiresAt <= Date.now())
    )
      return loadProvider(view);
  }
  for (const [index, tab] of tabs.entries()) {
    tab.addEventListener("click", () => selectView(tab.dataset.discoveryView));
    tab.addEventListener("keydown", (event) => {
      const next = {
        ArrowRight: (index + 1) % tabs.length,
        ArrowLeft: (index + tabs.length - 1) % tabs.length,
        Home: 0,
        End: tabs.length - 1,
      }[event.key];
      if (next === undefined) return;
      event.preventDefault();
      tabs[next].focus();
      selectView(tabs[next].dataset.discoveryView);
    });
  }
  function setupLink(host, provider) {
    const link = el("a", "text-button", names[provider] + "を設定する");
    link.href = "#settings";
    link.dataset.navigate = "settings-panel";
    link.dataset.focusTarget = "discovery-config-" + provider;
    host.append(document.createTextNode(" "), link);
  }
  function similarAvailability() {
    similarButton.disabled = !configured(s.config?.lastfm);
    if (similarButton.disabled)
      message(similarStatus, "設定からLast.fmを有効にすると利用できます。");
    else message(similarStatus);
    if (similarButton.disabled) setupLink(similarStatus, "lastfm");
  }
  async function loadProvider(provider, force = false) {
    if (!visible() || s.selected !== provider) return;
    const entry = s.panels.get(provider),
      settings = s.config?.[provider];
    if (entry.pending) return;
    if (!configured(settings)) {
      entry.items = [];
      entry.list.replaceChildren();
      entry.more.hidden = true;
      entry.timestamp.textContent = "";
      message(
        entry.feedback,
        "設定から" + names[provider] + "を有効にすると利用できます。",
      );
      entry.refresh.disabled = true;
      setupLink(entry.feedback, provider);
      return;
    }
    cancel(s, provider);
    const version = s.sequences.get(provider),
      controller = new AbortController();
    s.controllers.set(provider, controller);
    entry.pending = true;
    entry.refresh.disabled = true;
    message(entry.feedback, "取得中…");
    entry.card.setAttribute("aria-busy", "true");
    try {
      const result = await call(
        "GET",
        "/popular/" + provider + (force ? "?refresh=true" : ""),
        undefined,
        controller.signal,
      );
      if (version !== s.sequences.get(provider)) return;
      entry.items = Array.isArray(result.items) ? result.items : [];
      entry.loaded = ["ready", "stale"].includes(result.state);
      entry.expiresAt = result.expires_at
        ? Date.parse(result.expires_at)
        : Infinity;
      renderRows(entry.list, entry.items, entry.limit);
      entry.more.hidden = entry.limit >= entry.items.length;
      entry.timestamp.textContent = result.fetched_at
        ? `${countries[result.region] || result.region} · 最終取得 ${new Date(result.fetched_at).toLocaleString("ja-JP")}${result.cached ? " · キャッシュ" : ""}`
        : "";
      message(
        entry.feedback,
        result.message ||
          (!entry.items.length && result.state === "ready"
            ? "曲が見つかりませんでした。"
            : ""),
        ["error", "stale", "settings_changed"].includes(result.state),
      );
      if (["key_rejected", "key_unavailable"].includes(result.error_code))
        setupLink(entry.feedback, provider);
    } catch (error) {
      if (version === s.sequences.get(provider)) {
        entry.loaded = false;
        message(entry.feedback, "取得に失敗しました: " + error.message, true);
      }
    } finally {
      if (version === s.sequences.get(provider)) {
        entry.pending = false;
        entry.refresh.disabled = !configured(s.config?.[provider]);
        entry.card.removeAttribute("aria-busy");
      }
    }
  }
  async function load() {
    if (!visible()) return;
    message(overview, "連携設定を確認中…");
    try {
      await config();
      if (!visible()) return;
      if (
        !s.selected ||
        (!s.selectionExplicit && !configured(s.config[s.selected]))
      )
        s.selected =
          providers.find((p) => configured(s.config[p])) || "youtube";
      selectView(s.selected, false, false);
      similarAvailability();
      message(
        overview,
        providers.some((p) => configured(s.config[p]))
          ? "出典のページから曲を確認できます。"
          : "外部連携は任意です。設定画面でキーを登録すると利用できます。",
      );
      s.dirty = false;
      if (providers.includes(s.selected)) await loadProvider(s.selected);
    } catch (error) {
      message(overview, "設定を取得できません: " + error.message, true, load);
    }
  }
  similarForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (similarButton.disabled) return;
    const artist = similarForm.elements.namedItem("artist").value.trim(),
      track = similarForm.elements.namedItem("track").value.trim();
    if (!artist || !track) {
      message(similarStatus, "曲名とアーティスト名を入力してください。", true);
      return;
    }
    cancel(s, "similar");
    const version = s.sequences.get("similar"),
      controller = new AbortController();
    s.controllers.set("similar", controller);
    similarPending = true;
    similarButton.disabled = true;
    message(similarStatus, `「${track}」に近い曲を探しています…`);
    try {
      const result = await call(
        "GET",
        "/similar/lastfm?" + new URLSearchParams({ artist, track }),
        undefined,
        controller.signal,
      );
      if (version !== s.sequences.get("similar")) return;
      renderRows(similarResults, result.items || [], 20);
      message(
        similarStatus,
        result.message ||
          ((result.items || []).length
            ? `Last.fmで「${track}」／${artist} に近い曲を見つけました。`
            : "類似曲が見つかりませんでした。"),
        result.state !== "ready",
      );
    } catch (error) {
      if (version === s.sequences.get("similar"))
        message(similarStatus, "検索に失敗しました: " + error.message, true);
    } finally {
      if (version === s.sequences.get("similar")) {
        similarPending = false;
        similarButton.disabled = !configured(s.config?.lastfm);
      }
    }
  });
  document
    .getElementById("discovery-panel")
    .addEventListener("click", async (event) => {
      const button = event.target.closest?.(".discovery-download");
      const row = button?.closest(".discovery-item");
      const item = row && rowItems.get(row);
      if (!item || button.disabled || !configured(s.config?.lastfm)) return;
      cancelSource(s);
      let feedback = row.querySelector(".discovery-row-feedback");
      if (!feedback) {
        feedback = el("div", "discovery-feedback discovery-row-feedback");
        feedback.setAttribute("role", "status");
        feedback.setAttribute("aria-live", "polite");
        row.append(feedback);
      }
      button.disabled = true;
      s.sourceRequest = { button, feedback };
      const version = s.sequences.get("source"),
        controller = new AbortController();
      s.controllers.set("source", controller);
      message(feedback, "Last.fmに紐づく保存候補を確認中…");
      try {
        const result = await call(
          "POST",
          "/source/lastfm",
          { artist: item.artist, track: item.title },
          controller.signal,
        );
        if (version !== s.sequences.get("source")) return;
        if (
          !["ready", "stale"].includes(result.state) ||
          !/^https:\/\/www\.youtube\.com\/watch\?v=[A-Za-z0-9_-]{11}$/.test(
            result.youtube_url || "",
          )
        ) {
          message(
            feedback,
            result.message ||
              "保存候補が見つかりません。「YouTubeで探す」から取得先を選べます。",
            true,
          );
          return;
        }
        const detail = {
          url: result.youtube_url,
          title: item.title,
          artist: item.artist,
          accepted: false,
        };
        document.dispatchEvent(
          new document.defaultView.CustomEvent("workspace-import-video", {
            detail,
          }),
        );
        if (!detail.accepted)
          message(
            feedback,
            detail.message || "追加欄への移動を中止しました。",
            true,
          );
      } catch (error) {
        if (version === s.sequences.get("source"))
          message(feedback, "取得先を確認できません: " + error.message, true);
      } finally {
        if (version === s.sequences.get("source")) {
          button.disabled = false;
          s.sourceRequest = null;
        }
      }
    });
  document
    .getElementById("discovery-panel")
    .addEventListener("click", (event) => {
      const button = event.target.closest?.(".discovery-seed");
      const item = button && rowItems.get(button.closest(".discovery-item"));
      if (!item || !configured(s.config?.lastfm)) return;
      cancel(s, "similar");
      similarPending = false;
      similarResults.replaceChildren();
      similarButton.disabled = false;
      similarForm.elements.namedItem("artist").value = item.artist;
      similarForm.elements.namedItem("track").value = item.title;
      selectView("similar");
      similarForm.scrollIntoView?.({ block: "start" });
      similarForm.elements.namedItem("track").focus({ preventScroll: true });
      similarForm.requestSubmit();
    });
  for (const control of similarForm.querySelectorAll("input"))
    control.addEventListener("input", () => {
      cancel(s, "similar");
      similarPending = false;
      similarButton.disabled = !configured(s.config?.lastfm);
      similarResults.replaceChildren();
      message(similarStatus);
    });
  document.addEventListener("discovery-config-changed", (event) => {
    const provider = event.detail.provider;
    cancel(s, provider);
    const entry = s.panels.get(provider);
    entry.pending = false;
    entry.loaded = false;
    entry.items = [];
    entry.limit = 20;
    entry.list.replaceChildren();
    entry.timestamp.textContent = "";
    entry.more.hidden = true;
    entry.card.removeAttribute("aria-busy");
    s.dirty = true;
    if (provider === "lastfm") {
      cancelSource(s);
      cancel(s, "similar");
      similarPending = false;
      similarResults.replaceChildren();
      similarAvailability();
    }
    if (visible()) load();
  });
  const stop = () => {
    cancelSource(s);
    for (const name of [...providers, "similar"]) cancel(s, name);
    similarPending = false;
    for (const entry of s.panels.values()) {
      if (entry.pending) s.dirty = true;
      entry.pending = false;
      entry.refresh.disabled = !configured(
        s.config?.[entry.card.dataset.provider],
      );
      entry.card.removeAttribute("aria-busy");
    }
    similarButton.disabled = !configured(s.config?.lastfm);
  };
  const resume = () => {
    if (!visible()) stop();
    else if (s.dirty) load();
    else selectView(s.selected, false);
  };
  document.addEventListener("workspace-navigation", resume);
  document.addEventListener("visibilitychange", resume);
  window.addEventListener("pagehide", () => {
    s.away = true;
    stop();
  });
  window.addEventListener("pageshow", () => {
    s.away = false;
    resume();
  });
  load();
}
