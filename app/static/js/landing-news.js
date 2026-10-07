/* Lee publicaciones existentes; no dispara scraping ni ingesta. */
(function () {
  'use strict';
  const feed = document.querySelector('[data-news-feed]');
  if (!feed) return;
  const status = feed.querySelector('[data-news-status]');
  const retry = feed.querySelector('[data-news-retry]');
  const sections = Array.from(feed.querySelectorAll('[data-news-category]'));
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const carousels = new Map();
  // Muestras visuales locales: nunca se envían a la API ni se guardan en la base.
  const demoTitles = {
    salud: ['Prevención y cuidado de la salud en Misiones', 'Servicios de salud en las localidades', 'Hábitos para el bienestar de la comunidad'],
    turismo: ['Destinos para descubrir en Misiones', 'Naturaleza y recorridos por la región', 'Experiencias de turismo local'],
    festividades: ['Celebraciones y encuentros de la región', 'Cultura y tradiciones de las localidades', 'Actividades para compartir en comunidad']
  };

  function safeUrl(value) {
    if (typeof value !== 'string' || !value.trim()) return null;
    try {
      const url = new URL(value, window.location.origin);
      return ['http:', 'https:'].includes(url.protocol) ? url.href : null;
    } catch (_) { return null; }
  }

  function categoryOf(publication) {
    // El scraper actual guarda la categoría en fuente: "El Territorio (Policiales)".
    // categoria e imagen_url quedan admitidas para una futura ampliación de la API.
    const match = String(publication.fuente || '').match(/\(([^)]+)\)\s*$/);
    const category = String(publication.categoria || (match ? match[1] : 'sin-categoria'));
    return category.normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim().toLowerCase();
  }

  function card(publication, isDemo = false) {
    const article = document.createElement('article');
    article.className = 'news-card';
    const media = document.createElement('div');
    media.className = 'news-card__media';
    const fallback = document.createElement('span');
    fallback.className = 'news-card__fallback';
    fallback.innerHTML = '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3"><rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="8" cy="9" r="1.5"/><path d="m4 17 5-5 4 4 3-3 4 4"/></svg><span>El Territorio</span>';
    media.append(fallback);
    if (isDemo) fallback.querySelector('span').textContent = 'Vista de ejemplo';
    const imageUrl = safeUrl(publication.imagen_url);
    if (imageUrl) {
      const image = document.createElement('img');
      image.alt = ''; // El título contiguo identifica la noticia.
      image.loading = 'lazy';
      image.addEventListener('error', () => image.remove(), { once: true });
      image.src = imageUrl;
      media.append(image);
    }
    const body = document.createElement('div');
    body.className = 'news-card__body';
    const source = document.createElement('span');
    source.className = isDemo ? 'news-card__demo-badge' : 'news-card__source';
    source.textContent = isDemo ? 'Demostración' : (publication.fuente || 'El Territorio');
    const heading = document.createElement('h3');
    const url = safeUrl(publication.url);
    const title = publication.titulo || 'Noticia sin título';
    if (url && !isDemo) {
      const link = document.createElement('a');
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = title;
      heading.append(link);
    } else { heading.textContent = title; }
    body.append(source, heading);
    if (isDemo) {
      const note = document.createElement('p');
      note.className = 'news-card__demo-note';
      note.textContent = 'Contenido de ejemplo. No corresponde a una noticia publicada.';
      body.append(note);
    }
    if (url) {
      const link = document.createElement('a');
      link.className = 'news-card__link';
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = isDemo ? 'Visitar El Territorio ↗' : 'Leer en El Territorio ↗';
      body.append(link);
    }
    article.append(media, body);
    return article;
  }

  function carousel(section) {
    const track = section.querySelector('.news-track');
    const controls = section.querySelector('.news-category__controls');
    const pages = section.querySelector('.news-category__pages');
    const prev = section.querySelector('[data-news-prev]');
    const next = section.querySelector('[data-news-next]');
    let positions = [];
    function update() {
      const max = Math.max(0, track.scrollWidth - track.clientWidth);
      let current = 0;
      positions.forEach((position, index) => {
        if (Math.abs(position - track.scrollLeft) < Math.abs(positions[current] - track.scrollLeft)) current = index;
      });
      prev.disabled = track.scrollLeft <= 2;
      next.disabled = track.scrollLeft >= max - 2;
      Array.from(pages.children).forEach((dot, index) => dot.setAttribute('aria-pressed', String(index === current)));
    }
    function move(position) { track.scrollTo({ left: position, behavior: reduced ? 'auto' : 'smooth' }); }
    function refresh() {
      const max = Math.max(0, track.scrollWidth - track.clientWidth);
      positions = [0];
      // Cada página comienza en una tarjeta completa, también en móvil.
      const cards = Array.from(track.children);
      const origin = cards[0] ? cards[0].offsetLeft : 0;
      const step = cards.length > 1 ? cards[1].offsetLeft - origin : track.clientWidth;
      const visible = Math.max(1, Math.floor((track.clientWidth + 16) / Math.max(1, step)));
      for (let index = visible; index < cards.length && max > 2; index += visible) {
        const position = Math.min(cards[index].offsetLeft - origin, max);
        if (position > positions[positions.length - 1] + 2) positions.push(position);
      }
      controls.hidden = pages.hidden = max <= 2;
      pages.replaceChildren();
      positions.forEach((position, index) => {
        const dot = document.createElement('button');
        dot.type = 'button';
        dot.className = 'news-page-dot';
        dot.setAttribute('aria-label', 'Página ' + (index + 1));
        dot.setAttribute('aria-controls', track.id);
        dot.addEventListener('click', () => move(position));
        pages.append(dot);
      });
      update();
    }
    prev.addEventListener('click', () => move([...positions].reverse().find(position => position < track.scrollLeft - 2) ?? 0));
    next.addEventListener('click', () => move(positions.find(position => position > track.scrollLeft + 2) ?? positions[positions.length - 1]));
    track.addEventListener('scroll', update, { passive: true });
    if ('ResizeObserver' in window) new ResizeObserver(refresh).observe(track);
    else window.addEventListener('resize', refresh);
    refresh();
    return refresh;
  }

  async function load() {
    feed.setAttribute('aria-busy', 'true');
    status.textContent = 'Cargando noticias de El Territorio…';
    retry.hidden = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(feed.dataset.newsFeed, { headers: { Accept: 'application/json' }, signal: controller.signal });
      if (!response.ok) throw new Error('Respuesta no disponible');
      const payload = await response.json();
      if (payload.status !== 'success' || !Array.isArray(payload.data)) throw new Error('Formato no disponible');
      const groups = new Map(sections.map(section => [section.dataset.newsCategory, []]));
      payload.data.forEach(publication => {
        if (!publication || typeof publication !== 'object') return;
        const category = categoryOf(publication);
        // Mostrar únicamente las categorías elegidas, sin reclasificar otras noticias.
        if (groups.has(category)) groups.get(category).push(publication);
      });
      let demoCount = 0;
      sections.forEach(section => {
        const publications = groups.get(section.dataset.newsCategory);
        const isDemo = !publications.length && Boolean(demoTitles[section.dataset.newsCategory]);
        const items = isDemo
          ? demoTitles[section.dataset.newsCategory].map(titulo => ({ titulo, url: 'https://www.elterritorio.com.ar/' }))
          : publications;
        if (isDemo) demoCount += items.length;
        const track = section.querySelector('.news-track');
        const empty = section.querySelector('.news-category__empty');
        track.replaceChildren(...items.map(publication => card(publication, isDemo)));
        track.hidden = !items.length;
        empty.hidden = Boolean(items.length);
        empty.querySelector('p').textContent = 'No hay noticias de esta categoría entre las publicaciones recibidas.';
        if (items.length) {
          if (!carousels.has(section)) carousels.set(section, carousel(section));
          else carousels.get(section)();
        }
      });
      const visibleTotal = Array.from(groups.values()).reduce((total, publications) => total + publications.length, 0);
      status.textContent = visibleTotal
        ? 'El Territorio · ' + visibleTotal + ' noticias de las categorías seleccionadas'
        : 'No hay noticias de estas categorías entre las publicaciones recibidas.';
      if (demoCount) status.textContent += ' · ' + demoCount + ' tarjetas de demostración, fuera del conteo de noticias.';
    } catch (_) {
      status.textContent = 'No pudimos cargar las noticias. Intentá nuevamente.';
      retry.hidden = false;
    } finally {
      clearTimeout(timeout);
      feed.setAttribute('aria-busy', 'false');
    }
  }
  retry.addEventListener('click', load);
  load();
})();
