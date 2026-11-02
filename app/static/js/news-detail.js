(function () {
  'use strict';
  const reading = document.querySelector('[data-news-reading]');
  if (!reading) return;
  const content = reading.querySelector('[data-news-content]');
  const controls = reading.querySelector('[data-news-expand]');
  const button = reading.querySelector('[data-news-read-more]');
  const article = reading.closest('.news-detail__article');
  const image = article.querySelector('.news-detail__media img');
  let expanded = false;
  function refresh() {
    // Respetar el ancho real de la foto, sin recortarla ni cambiar su proporción.
    const width = image && image.getBoundingClientRect().width;
    reading.style.setProperty('--news-reading-width', width > 0 ? width + 'px' : '100%');
    const limit = parseFloat(getComputedStyle(reading).getPropertyValue('--news-preview-height')) || 340;
    const long = content.scrollHeight > limit + 32;
    controls.hidden = !long;
    reading.classList.toggle('is-collapsed', long && !expanded);
    button.textContent = expanded ? 'Leer menos' : 'Leer más';
    button.setAttribute('aria-expanded', String(!long || expanded));
  }
  button.addEventListener('click', () => {
    expanded = !expanded;
    refresh();
    // Al contraer, mantener el botón a la vista sin saltar al inicio de la noticia.
    if (!expanded) button.scrollIntoView({ block: 'nearest', behavior: 'auto' });
  });
  if (image) {
    image.addEventListener('load', refresh);
    if ('ResizeObserver' in window) new ResizeObserver(refresh).observe(image);
  }
  window.addEventListener('resize', refresh);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(refresh);
  refresh();

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
