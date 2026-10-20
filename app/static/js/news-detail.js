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
})();
