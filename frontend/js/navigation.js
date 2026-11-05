export function initNavigation() {
  const buttons = [...document.querySelectorAll('.tab-btn')];
  function show(id) {
    const target = document.getElementById(id);
    if (!target || !target.classList.contains('panel')) return;
    for (const panel of document.querySelectorAll('.layout > .panel')) {
      panel.classList.toggle('active', panel === target);
      panel.hidden = panel !== target;
    }
    for (const button of buttons) {
      const active = button.dataset.panel === id;
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    }
    const route = buttons.find(button => button.dataset.panel === id)?.dataset.route;
    if (route && location.hash !== '#' + route) history.replaceState({}, '', '#' + route);
    document.dispatchEvent(new document.defaultView.CustomEvent('workspace-navigation', {detail:{panel:id}}));
  }
  for (const button of buttons) button.addEventListener('click', () => show(button.dataset.panel));
  // Links created by a lazily opened workspace use the same navigation.
  document.addEventListener('click', event => {
    const button = event.target.closest?.('[data-navigate]');
    if (!button || button.disabled) return;
    const panel = document.getElementById(button.dataset.navigate);
    if (!panel?.classList.contains('panel')) return;
    event.preventDefault();
    show(panel.id);
    const destination = document.getElementById(button.dataset.focusTarget);
    if (destination && panel.contains(destination)) {
      destination.scrollIntoView?.({block: 'start'});
      destination.focus({preventScroll: true});
    }
  });
  const fromHash = () => show(buttons.find(button => '#' + button.dataset.route === location.hash)?.dataset.panel || 'playlists-panel');
  window.addEventListener('hashchange', fromHash);
  const openAddition = () => {
    show('playlists-panel');
    const panel = document.getElementById('sync-add-panel');
    panel.open = true;
    panel.scrollIntoView?.({behavior: 'smooth', block: 'nearest'});
    panel.querySelector('textarea, input')?.focus({preventScroll: true});
  };
  document.getElementById('open-sync-add')?.addEventListener('click', openAddition);
  document.getElementById('downloads-open-intake')?.addEventListener('click', openAddition);
  fromHash();
}
