(() => {
  const dropdown = document.getElementById('categories-dropdown');
  if (!dropdown) return;
  const trigger = dropdown.querySelector('button');
  const links = [...dropdown.querySelectorAll('a')];
  const panel = dropdown.querySelector('.categories-dropdown__panel');
  const close = () => {
    panel.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
  };
  trigger.addEventListener('click', () => {
    const returning = links.some(link => link.hash === window.location.hash);
    if (returning) {
      close();
      window.history.replaceState(null, '', window.location.pathname + window.location.search);
      sync();
      window.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
    } else {
      panel.hidden = !panel.hidden;
      trigger.setAttribute('aria-expanded', String(!panel.hidden));
    }
  });
  document.addEventListener('click', event => {
    if (!dropdown.contains(event.target)) close();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !panel.hidden) {
      close();
      trigger.focus();
    }
  });
  dropdown.addEventListener('focusout', () => {
    requestAnimationFrame(() => {
      if (!dropdown.contains(document.activeElement)) close();
    });
  });

  const sync = () => {
    const hash = window.location.hash || '#categorias';
    trigger.classList.toggle('is-current', hash === '#categorias');
    links.forEach(link => {
      if (link.hash === hash) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
    if (links.some(link => link.hash === hash)) {
      panel.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
    }
  };
  window.addEventListener('hashchange', sync);
  sync();
})();
