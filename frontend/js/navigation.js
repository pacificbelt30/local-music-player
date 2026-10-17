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
  }
  for (const button of buttons) button.addEventListener('click', () => show(button.dataset.panel));
  for (const button of document.querySelectorAll('[data-navigate]')) button.addEventListener('click', () => show(button.dataset.navigate));
  const fromHash = () => show(buttons.find(button => '#' + button.dataset.route === location.hash)?.dataset.panel || 'playlists-panel');
  window.addEventListener('hashchange', fromHash);
  document.getElementById('open-sync-add')?.addEventListener('click', () => {
    const panel = document.getElementById('sync-add-panel');
    panel.open = true;
    panel.scrollIntoView?.({behavior: 'smooth', block: 'nearest'});
    panel.querySelector('input')?.focus({preventScroll: true});
  });
  fromHash();
}
