/* Unifica el fallback cuando una imagen de noticia no puede cargarse. */
(function () {
  'use strict';

  function mostrarFallback(imagen) {
    if (imagen.dataset.fallbackMostrado === 'true') return;
    imagen.dataset.fallbackMostrado = 'true';
    imagen.hidden = true;
    const contenedor = imagen.closest('[data-news-image-container]');
    if (!contenedor) return;
    const fallback = contenedor.querySelector('[data-news-image-placeholder]');
    if (fallback) fallback.hidden = false;
    contenedor.querySelectorAll('[data-news-image-credit]').forEach(credito => {
      credito.hidden = true;
    });
  }

  document.addEventListener('error', evento => {
    const imagen = evento.target;
    if (imagen instanceof HTMLImageElement && imagen.matches('img[data-news-image-fallback]')) {
      mostrarFallback(imagen);
    }
  }, true);

  document.querySelectorAll('img[data-news-image-fallback]').forEach(imagen => {
    if (imagen.complete && imagen.naturalWidth === 0) mostrarFallback(imagen);
  });
}());
