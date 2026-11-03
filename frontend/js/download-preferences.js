import { api } from "./api.js";

const DEFAULTS = {default_audio_format: "mp3", default_audio_quality: "192", account_playlist_method: "url"};
const states = new WeakMap();
function state() {
  if (!states.has(document)) states.set(document, {values: {...DEFAULTS}, pending: null, loaded: false});
  return states.get(document);
}
function normalize(values) {
  const result = {...DEFAULTS};
  for (const key of Object.keys(result)) if (values[key] != null) result[key] = values[key];
  return result;
}
export function currentDownloadPreferences() { return {...state().values}; }
export function loadDownloadPreferences(reload = false) {
  const owner = document;
  const current = state();
  if (current.loaded && !reload) return Promise.resolve({...current.values});
  if (!current.pending) {
    current.pending = api.getSettings().then(values => {
      current.values = normalize(values);
      current.loaded = true;
      owner.dispatchEvent(new owner.defaultView.CustomEvent("download-preferences-changed", {detail: {...current.values}}));
      return {...current.values};
    }).finally(() => {current.pending = null;});
  }
  return current.pending;
}
export async function saveDownloadPreferences(values) {
  const owner = document;
  const current = state();
  const result = normalize(await api.updateSettings(values));
  current.values = result;
  current.loaded = true;
  owner.dispatchEvent(new owner.defaultView.CustomEvent("download-preferences-changed", {detail: result}));
  return result;
}
export function mediaDescription(format, quality) {
  return `${format.toUpperCase()} · ${["mp4", "webm"].includes(format) ? "動画" : quality === "best" ? "最高品質" : quality + " kbps"}`;
}
export function bindMediaDefaults(format, quality, summary, status) {
  let custom = false;
  const describe = () => {
    summary.textContent = mediaDescription(format.value, quality.value);
    quality.disabled = ["mp4", "webm"].includes(format.value);
  };
  const apply = values => {
    if (!custom) {
      format.value = values.default_audio_format;
      quality.value = values.default_audio_quality;
    }
    describe();
    if (status) status.textContent = "";
  };
  for (const control of [format, quality]) control.addEventListener("change", () => { custom = true; describe(); });
  document.addEventListener("download-preferences-changed", event => apply(event.detail));
  apply(currentDownloadPreferences());
  loadDownloadPreferences().then(apply).catch(error => {
    if (status) status.textContent = "設定を取得できませんでした。追加時に再確認します: " + error.message;
  });
}
