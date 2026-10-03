/* ==========================================================================
   TrendWatch · JavaScript compartido (vanilla)
   Cada módulo se inicializa solo si encuentra su elemento en el DOM,
   así el mismo archivo sirve para landing, login y categorías.
   ========================================================================== */
(function () {
  'use strict';

  const $  = (sel, ctx) => (ctx || document).querySelector(sel);
  const $$ = (sel, ctx) => Array.from((ctx || document).querySelectorAll(sel));
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- 1. Reveal al hacer scroll -------------------------------- */
  function initReveal() {
    const items = $$('.reveal');
    if (!items.length) return;
    if (reduced || !('IntersectionObserver' in window)) {
      items.forEach(el => el.classList.add('is-in'));
      return;
    }
    const io = new IntersectionObserver((entries) => {
      entries.forEach(e => {
        if (e.isIntersecting) { e.target.classList.add('is-in'); io.unobserve(e.target); }
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
    items.forEach((el, i) => { el.style.transitionDelay = Math.min(i % 6, 5) * 60 + 'ms'; io.observe(el); });
  }

  /* ---------- 2. Mostrar / ocultar contraseña -------------------------- */
  function initPassword() {
    const btn = $('[data-password-toggle]');
    if (!btn) return;
    const input = $('#' + btn.dataset.passwordToggle);
    if (!input) return;
    btn.addEventListener('click', () => {
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.setAttribute('aria-pressed', String(show));
      btn.setAttribute('aria-label', show ? 'Ocultar contraseña' : 'Mostrar contraseña');
      $('[data-eye-on]', btn).style.display  = show ? 'none' : 'block';
      $('[data-eye-off]', btn).style.display = show ? 'block' : 'none';
      input.focus();
    });
  }

  /* ---------- 3. Sidebar: colapsar (desktop) y abrir (mobile) ---------- */
  function initSidebar() {
    const shell   = $('#shell');
    const sidebar = $('#sidebar');
    if (!shell || !sidebar) return;

    const scrim    = $('#scrim');
    const burger   = $('#sidebar-open');
    const collapse = $('#sidebar-collapse');

    const closeMobile = () => {
      sidebar.classList.remove('is-open');
      scrim && scrim.classList.remove('is-open');
      burger && burger.setAttribute('aria-expanded', 'false');
    };

    burger && burger.addEventListener('click', () => {
      const open = sidebar.classList.toggle('is-open');
      scrim && scrim.classList.toggle('is-open', open);
      burger.setAttribute('aria-expanded', String(open));
      if (open) { const f = $('a', sidebar); f && f.focus(); }
    });

    scrim && scrim.addEventListener('click', closeMobile);

    collapse && collapse.addEventListener('click', () => {
      const c = shell.classList.toggle('is-collapsed');
      collapse.setAttribute('aria-expanded', String(!c));
      collapse.setAttribute('aria-label', c ? 'Expandir menú' : 'Contraer menú');
    });

    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && sidebar.classList.contains('is-open')) { closeMobile(); burger && burger.focus(); }
    });

    // al navegar en mobile el panel se cierra
    $$('a', sidebar).forEach(a => a.addEventListener('click', () => {
      if (window.innerWidth <= 820) closeMobile();
    }));
  }

  /* ---------- 4. Atajo "/" para el buscador ---------------------------- */
  function initSearchShortcut() {
    const input = $('#app-search-input');
    if (!input) return;
    document.addEventListener('keydown', e => {
      if (e.key === '/' && document.activeElement !== input && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) {
        e.preventDefault(); input.focus();
      }
    });
  }

  function initPublicNav() {
    const toggle = $('#public-nav-toggle');
    const links = $('#public-nav-links') || $('.nav__links');
    if (!toggle || !links) return;
    toggle.addEventListener('click', () => {
      const open = links.classList.toggle('is-open');
      toggle.setAttribute('aria-expanded', String(open));
      toggle.setAttribute('aria-label', open ? 'Cerrar navegación' : 'Abrir navegación');
    });
    $$('a', links).forEach(link => link.addEventListener('click', () => {
      links.classList.remove('is-open');
      toggle.setAttribute('aria-expanded', 'false');
    }));
  }

  /* ---------- 5. Filtros y segmentación (mock) ------------------------- */
  function initFilters() {
    const form = $('#filters');
    if (!form) return;

    const active  = $('#active-filters');
    const counter = $('#result-count');
    const total   = 128;                       // total ficticio sin filtros
    const state   = new Map();                 // clave -> etiqueta

    function label(sel) {
      return sel.options[sel.selectedIndex].text;
    }

    function render() {
      // los chips se reconstruyen desde el estado, no desde el DOM
      active.querySelectorAll('.chip--active').forEach(c => c.remove());
      state.forEach((text, key) => {
        const chip = document.createElement('span');
        chip.className = 'chip chip--active';
        chip.innerHTML = text + ' <button type="button" aria-label="Quitar filtro ' + text +
          '"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button>';
        chip.querySelector('button').addEventListener('click', () => {
          state.delete(key);
          const sel = form.querySelector('[name="' + key + '"]');
          if (sel) sel.selectedIndex = 0;
          if (key === 'categoria') $$('.cat').forEach(c => c.setAttribute('aria-pressed', 'false'));
          render();
        });
        active.insertBefore(chip, $('#clear-filters'));
      });

      $('#clear-filters').hidden = state.size === 0;
      $('#no-filters').hidden    = state.size !== 0;

      // conteo ficticio: cada filtro recorta el resultado
      const n = state.size === 0 ? total : Math.max(4, Math.round(total / Math.pow(1.8, state.size)));
      counter.textContent = n;
    }

    $$('select', form).forEach(sel => {
      sel.addEventListener('change', () => {
        if (sel.value === '') state.delete(sel.name);
        else state.set(sel.name, label(sel));
        if (sel.name === 'categoria') {
          $$('.cat').forEach(c => c.setAttribute('aria-pressed', String(c.dataset.cat === sel.value)));
        }
        render();
      });
    });

    $('#clear-filters').addEventListener('click', () => {
      state.clear();
      $$('select', form).forEach(s => s.selectedIndex = 0);
      $$('.cat').forEach(c => c.setAttribute('aria-pressed', 'false'));
      render();
    });

    // las cards de categoría actúan como filtro rápido
    $$('.cat').forEach(card => {
      card.addEventListener('click', () => {
        const on  = card.getAttribute('aria-pressed') === 'true';
        const sel = form.querySelector('[name="categoria"]');
        $$('.cat').forEach(c => c.setAttribute('aria-pressed', 'false'));
        if (on) { state.delete('categoria'); sel.selectedIndex = 0; }
        else {
          card.setAttribute('aria-pressed', 'true');
          sel.value = card.dataset.cat;
          state.set('categoria', card.dataset.label);
        }
        render();
      });
    });

    render();
  }

  /* ---------- 6. Orden de resultados (segmented control) --------------- */
  function initSeg() {
    $$('[data-seg]').forEach(group => {
      $$('button', group).forEach(btn => {
        btn.addEventListener('click', () => {
          $$('button', group).forEach(b => b.setAttribute('aria-pressed', 'false'));
          btn.setAttribute('aria-pressed', 'true');
        });
      });
    });
  }

  /* ---------- 7. Gráfico de tendencias en SVG -------------------------- */
  function initChart() {
    const svg = $('#tw-chart');
    if (!svg) return;

    const W = 760, H = 260, P = { t: 18, r: 14, b: 30, l: 34 };
    const labels = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];
    const series = [
      { name: 'Menciones',  color: '#3FD0B4', data: [1240, 1390, 1180, 1710, 2040, 2380, 2610] },
      { name: 'Alcance estimado', color: '#8EB69B', data: [820, 960, 900, 1120, 1380, 1520, 1640] }
    ];

    const NS  = 'http://www.w3.org/2000/svg';
    const max = Math.max(...series.flatMap(s => s.data)) * 1.12;
    const x = i => P.l + (i * (W - P.l - P.r)) / (labels.length - 1);
    const y = v => P.t + (1 - v / max) * (H - P.t - P.b);
    const el = (tag, attrs) => {
      const n = document.createElementNS(NS, tag);
      Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v));
      return n;
    };

    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.innerHTML = '';

    // degradado de área
    const defs = el('defs', {});
    const grad = el('linearGradient', { id: 'twArea', x1: '0', y1: '0', x2: '0', y2: '1' });
    grad.appendChild(el('stop', { offset: '0%',   'stop-color': '#3FD0B4', 'stop-opacity': '.32' }));
    grad.appendChild(el('stop', { offset: '100%', 'stop-color': '#3FD0B4', 'stop-opacity': '0' }));
    defs.appendChild(grad);
    svg.appendChild(defs);

    // grilla horizontal + eje Y
    for (let i = 0; i <= 4; i++) {
      const v  = (max / 4) * i;
      const gy = y(v);
      svg.appendChild(el('line', { x1: P.l, y1: gy, x2: W - P.r, y2: gy, stroke: 'rgba(218,241,222,.09)', 'stroke-width': 1 }));
      const t = el('text', { x: P.l - 9, y: gy + 4, 'text-anchor': 'end', fill: 'rgba(218,241,222,.4)', 'font-size': 10.5 });
      t.textContent = Math.round(v / 100) / 10 + 'k';
      svg.appendChild(t);
    }

    // etiquetas del eje X
    labels.forEach((l, i) => {
      const t = el('text', { x: x(i), y: H - 8, 'text-anchor': 'middle', fill: 'rgba(218,241,222,.45)', 'font-size': 11 });
      t.textContent = l;
      svg.appendChild(t);
    });

    // área bajo la serie principal
    const areaD = series[0].data.map((v, i) => (i ? 'L' : 'M') + x(i) + ' ' + y(v)).join(' ') +
                  ` L${x(labels.length - 1)} ${y(0)} L${x(0)} ${y(0)} Z`;
    svg.appendChild(el('path', { d: areaD, fill: 'url(#twArea)' }));

    // líneas
    series.forEach((s, si) => {
      const d = s.data.map((v, i) => (i ? 'L' : 'M') + x(i) + ' ' + y(v)).join(' ');
      svg.appendChild(el('path', {
        d, fill: 'none', stroke: s.color, 'stroke-width': si ? 1.6 : 2.4,
        'stroke-linecap': 'round', 'stroke-linejoin': 'round',
        'stroke-dasharray': si ? '5 6' : '', class: si ? '' : 'draw-line', opacity: si ? .75 : 1
      }));
      if (!si) s.data.forEach((v, i) => svg.appendChild(el('circle', { cx: x(i), cy: y(v), r: 3.4, fill: '#051F20', stroke: s.color, 'stroke-width': 2 })));
    });

    // línea guía + tooltip
    const guide = el('line', { x1: 0, y1: P.t, x2: 0, y2: H - P.b, stroke: 'rgba(63,208,180,.45)', 'stroke-width': 1, opacity: 0 });
    svg.appendChild(guide);

    const tip = $('#chart-tip');
    const wrap = svg.parentElement;

    function move(clientX) {
      const box = svg.getBoundingClientRect();
      const rel = ((clientX - box.left) / box.width) * W;
      let i = Math.round(((rel - P.l) / (W - P.l - P.r)) * (labels.length - 1));
      i = Math.max(0, Math.min(labels.length - 1, i));
      guide.setAttribute('x1', x(i)); guide.setAttribute('x2', x(i)); guide.setAttribute('opacity', 1);
      tip.style.opacity = 1;
      tip.style.left = (x(i) / W) * box.width + 'px';
      tip.style.top  = (y(series[0].data[i]) / H) * box.height + 'px';
      tip.innerHTML  = '<b>' + series[0].data[i].toLocaleString('es-AR') + '</b> menciones<br>' + labels[i] + ' · Misiones';
    }
    function leave() { guide.setAttribute('opacity', 0); tip.style.opacity = 0; }

    wrap.addEventListener('mousemove', e => move(e.clientX));
    wrap.addEventListener('mouseleave', leave);
    wrap.addEventListener('touchmove', e => { move(e.touches[0].clientX); }, { passive: true });
    wrap.addEventListener('touchend', leave);
  }

  /* ---------- 8. Votos de relevancia (mock) ---------------------------- */
  function initVotes() {
    $$('[data-vote]').forEach(btn => {
      btn.addEventListener('click', () => {
        const on = btn.getAttribute('aria-pressed') === 'true';
        btn.setAttribute('aria-pressed', String(!on));
        const out = btn.parentElement.querySelector('[data-vote-count]');
        if (out) out.textContent = Number(out.textContent) + (on ? -1 : 1);
      });
    });
  }

  /* ---------- 9. Interacciones de la landing institucional ------------- */
  function initLanding() {
    const landing = $('.landing-main');
    if (!landing) return;

    const revealItems = $$('section:not(.landing-section--cta), .process-card, .capability-card, .profile-card, .technology-panel, .landing-cta', landing);
    revealItems.forEach((item, index) => {
      item.classList.add('landing-reveal');
      item.style.transitionDelay = Math.min(index % 5, 4) * 70 + 'ms';
    });

    if (reduced || !('IntersectionObserver' in window)) {
      revealItems.forEach(item => item.classList.add('is-visible'));
    } else {
      const io = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            io.unobserve(entry.target);
          }
        });
      }, { threshold: 0.12, rootMargin: '0px 0px -35px 0px' });
      revealItems.forEach(item => io.observe(item));
    }

    $$('a[href^="#"]', landing).forEach(link => {
      link.addEventListener('click', event => {
        const target = $(link.getAttribute('href'));
        if (!target) return;
        event.preventDefault();
        target.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' });
        target.setAttribute('tabindex', '-1');
        target.focus({ preventScroll: true });
      });
    });
  }

  /* ---------- Arranque ------------------------------------------------- */
  document.addEventListener('DOMContentLoaded', function () {
    initReveal();
    initPassword();
    initSidebar();
    initSearchShortcut();
    initPublicNav();
    initFilters();
    initSeg();
    initChart();
    initVotes();
    initLanding();
  });
})();
