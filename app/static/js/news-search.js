/* Mejora progresiva: el formulario GET y el enlace alternativo no dependen de JS. */
(function () {
  'use strict';
  const toggle = document.querySelector('[data-search-toggle]');
  const row = document.getElementById('public-search-row');
  if (toggle && row) {
    const fallback = document.querySelector('[data-search-fallback]');
    const input = row.querySelector('input[name="q"]');
    const close = restore => {
      row.hidden = true;
      toggle.setAttribute('aria-expanded', 'false');
      if (restore) toggle.focus();
    };
    toggle.hidden = false;
    if (fallback) fallback.hidden = true;
    toggle.addEventListener('click', () => {
      if (!row.hidden) { close(true); return; }
      const menu = document.getElementById('public-nav-toggle');
      if (menu && menu.getAttribute('aria-expanded') === 'true') menu.click();
      document.querySelectorAll('.account-notifications__panel').forEach(panel => { panel.hidden = true; });
      document.querySelectorAll('[data-account-notifications]').forEach(button => button.setAttribute('aria-expanded', 'false'));
      row.hidden = false;
      toggle.setAttribute('aria-expanded', 'true');
      if (input) input.focus();
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !row.hidden && !event.defaultPrevented) {
        event.preventDefault();
        close(true);
      }
    });
    document.querySelectorAll('#public-nav-toggle, .nav__act').forEach(control => {
      control.addEventListener('click', () => { if (!row.hidden) close(false); });
    });
  }
  document.querySelectorAll('[data-search-image]').forEach(img => {
    const hide = () => { img.closest('.search-result__image').hidden = true; };
    img.addEventListener('error', hide);
    if (img.complete && img.naturalWidth === 0) hide();
  });
}());
