(function () {
  'use strict';
  const reading = document.querySelector('[data-news-reading]');
  const controls = reading?.querySelector('[data-news-expand]');
  const button = reading?.querySelector('[data-news-read-more]');
  const more = reading?.querySelector('[data-news-more]');
  if (more && controls && button) {
    let expanded = false;
    button.addEventListener('click', () => {
      expanded = !expanded;
      const previousScroll = window.scrollY;
      more.hidden = !expanded;
      button.textContent = expanded ? 'Leer menos' : 'Leer más';
      button.setAttribute('aria-expanded', String(expanded));
      if (expanded) window.scrollTo(0, previousScroll);
      else button.scrollIntoView({ block: 'nearest', behavior: 'auto' });
    });
    // Plegar sólo después de registrar el control; si falla la inicialización,
    // el contenido entregado por el servidor continúa visible.
    more.hidden = true;
    controls.hidden = false;
  }

  // Conservar el scroll al valorar o guardar: el servidor sigue siendo la fuente
  // de verdad y la respuesta actualiza únicamente el bloque correspondiente.
  document.addEventListener('submit', async event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    const rating = form.closest('#valoraciones');
    const saving = form.closest('.news-save-action');
    if (!rating && !saving) return;
    if (form.dataset.nativeSubmit === 'true') return;
    event.preventDefault();
    const submitter = event.submitter;
    const data = new FormData(form);
    if (submitter && submitter.name) data.set(submitter.name, submitter.value);
    const buttons = [...form.querySelectorAll('button')];
    buttons.forEach(control => { control.disabled = true; });
    try {
      const response = await fetch(form.action, {
        method: 'POST', body: data, credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      });
      if (!response.ok) throw new Error('No se pudo actualizar');
      const updated = new DOMParser().parseFromString(await response.text(), 'text/html');
      const selector = rating ? '#valoraciones' : '.news-save-action';
      const replacement = updated.querySelector(selector);
      if (!replacement) throw new Error('Respuesta inesperada');
      document.querySelector(selector).replaceWith(replacement);
      const focus = rating ? replacement.querySelector(`button[value="${submitter?.value || ''}"]`)
        : replacement.querySelector('button');
      focus?.focus({ preventScroll: true });
    } catch (_) {
      buttons.forEach(control => { control.disabled = false; });
      form.dataset.nativeSubmit = 'true';
      form.requestSubmit(submitter || undefined);
    }
  });
})();
