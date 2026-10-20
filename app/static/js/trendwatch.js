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
    $$('[data-password-toggle]').forEach(btn => {
      const input = $('#' + btn.dataset.passwordToggle);
      if (!input) return;
      const setVisible = show => {
        input.type = show ? 'text' : 'password';
        btn.setAttribute('aria-pressed', String(show));
        btn.setAttribute('aria-label', show ? 'Ocultar contraseña' : 'Mostrar contraseña');
        $('[data-eye-on]', btn).style.display = show ? 'block' : 'none';
        $('[data-eye-off]', btn).style.display = show ? 'none' : 'block';
      };
      setVisible(false);
      btn.hidden = false;
      btn.addEventListener('click', () => setVisible(input.type === 'password'));
      const modal = btn.closest('.login-modal');
      if (modal) modal.addEventListener('auth:reset', () => setVisible(false));
      const form = btn.closest('form');
      if (form) {
        form.addEventListener('submit', () => setVisible(false));
        form.querySelectorAll('[data-auth-register], [data-auth-login]').forEach(switcher => {
          switcher.addEventListener('click', () => setVisible(false));
        });
      }
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
    const navLinks = $$('nav a', sidebar);

    const setCurrentNav = link => {
      navLinks.forEach(item => {
        if (item === link) item.setAttribute('aria-current', 'page');
        else item.removeAttribute('aria-current');
      });
    };

    const syncCurrentNav = () => {
      const link = navLinks.find(item => item.getAttribute('href') === window.location.hash);
      if (link) setCurrentNav(link);
    };

    navLinks.forEach(link => {
      link.addEventListener('click', () => setCurrentNav(link));
    });

    syncCurrentNav();
    window.addEventListener('hashchange', syncCurrentNav);

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

  function initLoginModal() {
    const modal = $('#login-modal');
    if (!modal) return;

    const triggers = $$('a[href="#login-modal"], a[href$="#login-modal"]');
    const closeButtons = $$('[data-login-close]', modal);
    const username = $('#id_modal_username', modal);
    let lastFocused = null;

    const open = () => {
      if (!modal.hidden && modal.classList.contains('is-open')) return;
      lastFocused = document.activeElement;
      modal.hidden = false;
      document.body.classList.add('login-modal-open');
      requestAnimationFrame(() => modal.classList.add('is-open'));
      username && username.focus();
    };

    const close = () => {
      if (modal.hidden) return;
      modal.classList.remove('is-open');
      document.body.classList.remove('login-modal-open');
      modal.hidden = true;
      modal.dispatchEvent(new Event('auth:reset'));
      if (window.location.hash === '#login-modal') {
        history.replaceState(null, '', window.location.pathname + window.location.search);
      }
      if (lastFocused && typeof lastFocused.focus === 'function') lastFocused.focus();
    };

    triggers.forEach(trigger => trigger.addEventListener('click', event => {
      event.preventDefault();
      open();
    }));
    closeButtons.forEach(button => button.addEventListener('click', close));

    modal.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        event.preventDefault();
        close();
        return;
      }
      if (event.key !== 'Tab') return;

      const focusable = $$('button:not([disabled]), input:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])', modal)
        .filter(element => element.getClientRects().length > 0);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });

    if (window.location.hash === '#login-modal' || !modal.hidden) open();
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
    initLoginModal();
    initLanding();
  });
})();
