const states = {
  error: {label: "同期エラー", color: "warning"},
  disconnected: {label: "同期先の接続待ち", color: "warning"},
  unknown: {label: "同期状態を確認中", color: "text-muted"},
  paused: {label: "一時停止中", color: "text-muted"},
  unshared: {label: "共有先が未設定", color: "text-muted"},
};

export function folderPresentation(folder) {
  if (folder.paused) return states.paused;
  if (states[folder.state]) return states[folder.state];
  if (folder.state === "synced") return {label: "同期完了", color: "success"};
  if (folder.state === "syncing") {
    const pct = folder.completion_pct == null ? "" : ` ${Math.round(folder.completion_pct)}%`;
    return {label: `同期中${pct}`, color: "warning"};
  }
  return states.unknown;
}

export function badgePresentation(status) {
  if (!status.available) return {text: "Syncthing: off", title: status.reason || "接続できません", className: "syncthing-badge"};
  const view = folderPresentation(status);
  const details = [`デバイス ${status.connected_devices ?? 0}/${status.total_devices ?? 0} 接続中`, ...(status.errors || [])];
  if (status.state === "syncing") details.unshift(`残り ${status.need_bytes_fmt || "?"}、${status.need_items || 0} 項目`);
  return {text: status.state === "synced" ? "Synced" : view.label, title: details.join(" | "),
          className: "syncthing-badge" + (status.state === "synced" ? " ok" : ["syncing", "error", "disconnected"].includes(status.state) ? " syncing" : "")};
}
