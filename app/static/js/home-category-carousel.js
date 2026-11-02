/* Navega las tarjetas ya renderizadas por Django; no descarga otro listado. */
(function () {
  'use strict';
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  document.querySelectorAll('[data-home-category]').forEach(section => {
    const track = section.querySelector('.news-track');
    if (!track || !track.children.length) return;
    const controls = section.querySelector('.news-category__controls');
    const pages = section.querySelector('.news-category__pages');
    const previous = section.querySelector('[data-news-prev]');
    const next = section.querySelector('[data-news-next]');
    let positions = [0];

    function currentPage() {
      return positions.reduce((best, position, index) =>
        Math.abs(position - track.scrollLeft) < Math.abs(positions[best] - track.scrollLeft) ? index : best, 0);
    }

    function update() {
      const maximum = Math.max(0, track.scrollWidth - track.clientWidth);
      previous.disabled = track.scrollLeft <= 2;
      next.disabled = track.scrollLeft >= maximum - 2;
      [...pages.children].forEach((dot, index) => dot.setAttribute('aria-pressed', String(index === currentPage())));
    }

    function move(position) {
      track.scrollTo({ left: position, behavior: reducedMotion ? 'auto' : 'smooth' });
    }

    function refresh() {
      const cards = [...track.children];
      const maximum = Math.max(0, track.scrollWidth - track.clientWidth);
      const start = cards[0].offsetLeft;
      const step = cards.length > 1 ? cards[1].offsetLeft - start : track.clientWidth;
      const visible = Math.max(1, Math.round(track.clientWidth / Math.max(1, step)));
      positions = [0];
      for (let index = visible; index < cards.length; index += visible) {
        const position = Math.min(cards[index].offsetLeft - start, maximum);
        if (position > positions[positions.length - 1] + 2) positions.push(position);
      }
      controls.hidden = pages.hidden = maximum <= 2;
      pages.replaceChildren();
      positions.forEach((position, index) => {
        const dot = document.createElement('button');
        dot.type = 'button';
        dot.className = 'news-page-dot';
        dot.setAttribute('aria-label', 'Página ' + (index + 1) + ' de ' + section.querySelector('h2').textContent);
        dot.setAttribute('aria-controls', track.id);
        dot.addEventListener('click', () => move(position));
        pages.append(dot);
      });
      update();
    }

    previous.addEventListener('click', () => move([...positions].reverse().find(position => position < track.scrollLeft - 2) ?? 0));
    next.addEventListener('click', () => move(positions.find(position => position > track.scrollLeft + 2) ?? positions[positions.length - 1]));
    track.addEventListener('scroll', update, { passive: true });
    if ('ResizeObserver' in window) new ResizeObserver(refresh).observe(track);
    else window.addEventListener('resize', refresh);
    refresh();
  });
})();
