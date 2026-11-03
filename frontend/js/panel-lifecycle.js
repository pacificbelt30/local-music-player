// Start a panel's initial work only when it can actually be seen. The guard is
// set before calling start so navigation/visibility events cannot start it twice.
export function whenPanelVisible(id, start) {
  let started = false;
  const check = () => {
    if (
      started ||
      document.hidden ||
      !document.getElementById(id)?.classList.contains("active")
    )
      return;
    started = true;
    document.removeEventListener("workspace-navigation", check);
    document.removeEventListener("visibilitychange", check);
    window.removeEventListener("pageshow", check);
    start();
  };
  document.addEventListener("workspace-navigation", check);
  document.addEventListener("visibilitychange", check);
  window.addEventListener("pageshow", check);
  check();
}
