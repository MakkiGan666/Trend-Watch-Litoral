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

/* Cada campo conserva su controlador: no comparte respuestas ni selección. */
(function (root) {
  'use strict';
  class Sugerencias {
    constructor(form, dependencies = {}) {
      this.form = form;
      this.input = form.querySelector('input[name="q"]');
      this.fetch = dependencies.fetch || root.fetch.bind(root);
      this.schedule = dependencies.setTimeout || root.setTimeout.bind(root);
      this.unschedule = dependencies.clearTimeout || root.clearTimeout.bind(root);
      this.version = 0;
      this.active = -1;
      this.options = [];
      this.composing = false;
      this.panel = document.createElement('div');
      this.panel.id = this.input.id + '-suggestions';
      this.panel.className = 'search-suggestions';
      this.panel.hidden = true;
      this.panel.setAttribute('role', 'listbox');
      this.panel.setAttribute('aria-label', 'Sugerencias de búsqueda y noticias');
      form.append(this.panel);
      this.status = document.createElement('span');
      this.status.className = 'sr-only';
      this.status.setAttribute('role', 'status');
      form.append(this.status);
      this.input.setAttribute('role', 'combobox');
      this.input.setAttribute('aria-autocomplete', 'list');
      this.input.setAttribute('aria-controls', this.panel.id);
      this.input.setAttribute('aria-expanded', 'false');
      this.input.setAttribute('autocomplete', 'off');
      this.input.addEventListener('compositionstart', () => { this.composing = true; this.close(); });
      this.input.addEventListener('compositionend', () => { this.composing = false; this.changed(); });
      this.input.addEventListener('input', () => { if (!this.composing) this.changed(); });
      // Chips de la búsqueda ya enviada: sólo valen mientras el texto sea esa búsqueda.
      this.pageHashtags = form.querySelector('.search-hashtags--page');
      if (this.pageHashtags) {
        const normal = value => value.normalize('NFC').trim().replace(/\s+/g, ' ').toLocaleLowerCase('es');
        const sync = () => { this.pageHashtags.hidden = normal(this.input.value) !== normal(this.pageHashtags.dataset.consulta || ''); };
        this.input.addEventListener('input', sync);
        this.input.addEventListener('search', sync);
        root.addEventListener('pageshow', sync); // "Atrás" restaura el texto del campo
        sync();
      }
      this.input.addEventListener('keydown', event => this.key(event));
      this.input.addEventListener('blur', () => this.close());
      this.input.addEventListener('search', () => this.changed());
      form.addEventListener('submit', () => this.close());
      // Mantener foco con mouse; un gesto táctil de desplazamiento no selecciona.
      this.panel.addEventListener('pointerdown', event => {
        const option = event.target.closest('[role="option"]');
        if (!option || event.button !== 0) return;
        if (event.pointerType === 'touch') {
          this.touch = { id: event.pointerId, x: event.clientX, y: event.clientY, option };
        } else event.preventDefault();
      });
      this.panel.addEventListener('pointermove', event => {
        if (this.touch && this.touch.id === event.pointerId &&
            Math.hypot(event.clientX - this.touch.x, event.clientY - this.touch.y) > 10) this.touch = null;
      });
      this.panel.addEventListener('pointercancel', () => { this.touch = null; });
      this.panel.addEventListener('pointerup', event => {
        const touch = this.touch;
        this.touch = null;
        if (touch && touch.id === event.pointerId && touch.option === event.target.closest('[role="option"]')) {
          event.preventDefault();
          this.select(Number(touch.option.dataset.index));
        }
      });
      this.panel.addEventListener('click', event => {
        const option = event.target.closest('[role="option"]');
        if (option && event.button === 0 && event.pointerType !== 'touch') this.select(Number(option.dataset.index));
      });
      const row = form.closest('#public-search-row');
      if (row && root.MutationObserver) new root.MutationObserver(() => {
        if (row.hidden) this.close();
      }).observe(row, { attributes: true, attributeFilter: ['hidden'] });
    }
    close() {
      this.version++;
      this.touch = null;
      this.unschedule(this.timer);
      this.timer = null;
      if (this.controller) this.controller.abort();
      this.controller = null;
      this.panel.hidden = true;
      this.active = -1;
      this.options = [];
      this.input.setAttribute('aria-expanded', 'false');
      this.input.removeAttribute('aria-activedescendant');
      this.status.textContent = '';
    }
    changed() {
      this.close();
      const q = this.input.value.normalize('NFC').trim().replace(/\s+/g, ' ');
      if ([...q].length < 2 || [...q].length > 150 || q.split(' ').length > 10) return;
      const version = this.version;
      this.timer = this.schedule(() => { this.timer = null; this.request(q, version); }, 300);
    }
    async json(path, q, signal) {
      const url = new URL(path, root.location.origin);
      url.searchParams.set('q', q);
      const response = await this.fetch(url, { signal, headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error('Respuesta no disponible');
      return response.json();
    }
    async request(q, version) {
      this.controller = new AbortController();
      const controller = this.controller;
      const timeout = this.schedule(() => controller.abort(), 5000);
      try {
        // Las sugerencias se muestran apenas llegan; los hashtags (más costosos)
        // se suman arriba después. Si fallan, las sugerencias siguen igual.
        const hashtagsPath = this.form.dataset.hashtagsUrl;
        const pendientes = hashtagsPath
          ? this.json(hashtagsPath, q, controller.signal).catch(() => null) : Promise.resolve(null);
        const data = await this.json(this.form.dataset.suggestionsUrl, q, controller.signal).catch(() => null);
        if (version !== this.version || controller.signal.aborted) return;
        if (data) this.render(data, null);
        const hashtags = await pendientes;
        if (version !== this.version || controller.signal.aborted) return;
        if (hashtags) this.render(data, hashtags);
        else if (!data) this.close();
      } catch (_) {
        if (version === this.version) this.close(); // El formulario sigue disponible.
      } finally {
        this.unschedule(timeout);
        if (this.controller === controller) this.controller = null;
      }
    }
    render(data, hashtags) {
      // Al sumar los hashtags se conserva la opción marcada con el teclado.
      const previa = this.active >= 0 ? this.options[this.active] : null;
      const clave = option => option.type + '\u0000' + (option.item.consulta || option.item.url || option.item.valor);
      const marcada = previa ? clave(previa) : null;
      this.panel.replaceChildren();
      this.options = [];
      if (!data || typeof data !== 'object') data = {};
      if (!hashtags || typeof hashtags !== 'object') hashtags = {};
      const consultaHashtags = typeof hashtags.consulta === 'string' ? hashtags.consulta : '';
      for (const [label, items, type] of [
        // Siempre primero: los hashtags quedan por encima de las sugerencias.
        ['Explorar por hashtags', Array.isArray(hashtags.hashtags) && consultaHashtags ? hashtags.hashtags.slice(0, 8) : [], 'hashtag'],
        ['Sugerencias de búsqueda', Array.isArray(data.terminos) ? data.terminos.slice(0, 5) : [], 'termino'],
        ['Noticias relacionadas', Array.isArray(data.noticias) ? data.noticias.slice(0, 4) : [], 'noticia']
      ]) {
        if (!items.length) continue;
        const group = document.createElement('div');
        group.setAttribute('role', 'group');
        group.setAttribute('aria-label', label);
        const heading = document.createElement('div');
        heading.className = 'search-suggestions__heading';
        heading.setAttribute('aria-hidden', 'true');
        heading.textContent = label;
        group.append(heading);
        if (type === 'hashtag') group.className = 'search-suggestions__hashtags';
        for (const item of items) {
          if (!item || typeof item !== 'object') continue;
          const text = type === 'noticia' ? item.titulo : item.texto;
          const target = type === 'termino' ? item.consulta : type === 'hashtag' ? item.valor : item.url;
          if (typeof text !== 'string' || !text.trim() ||
              typeof target !== 'string' || !target.trim()) continue;
          if (type === 'hashtag' && (!/^(ent|cat|dep):[^\s:]{1,80}$/u.test(target) ||
              !Number.isInteger(item.total) || item.total < 1)) continue;
          if (type === 'noticia') {
            let url;
            try { url = new URL(target, root.location.origin); }
            catch (_) { continue; }
            if (url.origin !== root.location.origin || !/^\/noticia\/[1-9]\d*\/$/.test(url.pathname)) continue;
          }
          const index = this.options.length;
          const option = document.createElement('div');
          option.id = this.panel.id + '-' + index;
          option.dataset.index = String(index);
          option.setAttribute('role', 'option');
          option.setAttribute('aria-selected', 'false');
          option.textContent = text;
          if (type === 'hashtag') {
            option.className = 'hashtag-chip';
            const count = document.createElement('span');
            count.className = 'hashtag-chip__count';
            count.setAttribute('aria-hidden', 'true');
            count.textContent = String(item.total);
            option.append(count);
            option.setAttribute('aria-label', text + ', filtrar ' + item.total + (item.total === 1 ? ' noticia' : ' noticias'));
            if (typeof item.descripcion === 'string') option.title = item.descripcion;
          }
          group.append(option);
          this.options.push({ element: option, item, type, consulta: consultaHashtags });
        }
        if (group.childElementCount > 1) this.panel.append(group);
      }
      this.active = marcada === null ? -1 : this.options.findIndex(option => clave(option) === marcada);
      if (this.active >= 0) {
        this.options[this.active].element.setAttribute('aria-selected', 'true');
        this.input.setAttribute('aria-activedescendant', this.options[this.active].element.id);
      } else this.input.removeAttribute('aria-activedescendant');
      this.panel.hidden = this.options.length === 0;
      this.input.setAttribute('aria-expanded', String(!this.panel.hidden));
      this.status.textContent = this.options.length ? this.options.length + ' sugerencias disponibles. Usá las flechas para recorrerlas.' : '';
    }
    key(event) {
      if (event.isComposing || this.composing) return;
      if (event.key === 'Escape' && (!this.panel.hidden || this.timer || this.controller)) {
        event.preventDefault(); event.stopPropagation(); this.close(); return;
      }
      if (this.panel.hidden || !this.options.length) return;
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const step = event.key === 'ArrowDown' ? 1 : -1;
        this.active = this.active < 0 ? (step > 0 ? 0 : this.options.length - 1)
          : (this.active + step + this.options.length) % this.options.length;
        this.options.forEach((option, index) => option.element.setAttribute('aria-selected', String(index === this.active)));
        const option = this.options[this.active].element;
        this.input.setAttribute('aria-activedescendant', option.id);
        option.scrollIntoView({ block: 'nearest' });
      } else if (event.key === 'Enter' && this.active >= 0) {
        event.preventDefault(); this.select(this.active);
      }
    }
    select(index) {
      const selected = this.options[index];
      if (!selected) return;
      this.close();
      if (selected.type === 'termino') {
        this.input.value = selected.item.consulta;
        this.form.requestSubmit();
      } else if (selected.type === 'hashtag') {
        // Filtro real: la misma búsqueda del formulario, restringida con h.
        const url = new URL(this.form.getAttribute('action'), root.location.origin);
        url.searchParams.set('q', selected.consulta);
        url.searchParams.set('h', selected.item.valor);
        root.location.assign(url.href);
      } else root.location.assign(selected.item.url);
    }
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = Sugerencias;
  else document.querySelectorAll('[data-suggestions-url]').forEach(form => new Sugerencias(form));
}(typeof window === 'undefined' ? globalThis : window));
