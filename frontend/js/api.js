const BASE = "/api/v1";

async function request(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(BASE + path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  // URLs
  addUrl: (payload) => request("POST", "/urls", payload),
  listUrls: () => request("GET", "/urls"),
  deleteUrl: (id, deleteFiles = false) => request("DELETE", `/urls/${id}?delete_files=${deleteFiles}`),

  // Queue
  listQueue: (status) => request("GET", "/queue" + (status ? `?status=${status}` : "")),
  cancelJob: (id) => request("DELETE", `/queue/${id}`),
  retryJob: (id) => request("POST", `/queue/${id}/retry`),

  // Tracks
  listTracks: (params = {}) => {
    const q = new URLSearchParams(params).toString();
    return request("GET", "/tracks" + (q ? "?" + q : ""));
  },
  updateTrack: (id, data) => request("PATCH", `/tracks/${id}`, data),
  deleteTrack: (id, deleteFile = false) => request("DELETE", `/tracks/${id}?delete_file=${deleteFile}`),

  // Syncthing
  syncthingStatus: () => request("GET", "/syncthing/status"),

  // Health
  health: () => request("GET", "/health"),

  // YouTube Auth
  youtubeAuthUrl: () => request("GET", "/youtube/auth/url"),
  youtubeAuthStatus: () => request("GET", "/youtube/auth/status"),
  youtubeRevokeAuth: () => request("DELETE", "/youtube/auth"),
  youtubeSetToken: (payload) => request("POST", "/youtube/auth/token", payload),

  // YouTube Playlists (account)
  youtubeListAccountPlaylists: () => request("GET", "/youtube/playlists"),

  // YouTube Sync configs
  youtubeListSyncs: () => request("GET", "/youtube/syncs"),
  youtubeCreateSync: (payload) => request("POST", "/youtube/syncs", payload),
  youtubeUpdateSync: (id, payload) => request("PATCH", `/youtube/syncs/${id}`, payload),
  youtubeDeleteSync: (id, deleteFiles = false) => request("DELETE", `/youtube/syncs/${id}?delete_files=${deleteFiles}`),
  youtubeSyncNow: (id) => request("POST", `/youtube/syncs/${id}/run`),

  // YouTube Sync tracks
  youtubeListSyncTracks: (syncId) => request("GET", `/youtube/syncs/${syncId}/tracks`),

  // Settings
  getSettings: () => request("GET", "/settings"),
  updateSettings: (payload) => request("PATCH", "/settings", payload),
};

// SSE for queue progress
export function subscribeQueueEvents(onData) {
  const es = new EventSource(BASE + "/queue/events");
  es.onmessage = (e) => {
    try { onData(JSON.parse(e.data)); } catch {}
  };
  es.onerror = () => {};
  return es;
}
