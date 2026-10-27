(function () {
  'use strict';
  const wrapper = document.querySelector('[data-dashboard-calendar]');
  if (!wrapper) return;
  const form = wrapper.closest('form');
  const input = wrapper.querySelector('#dashboard-date');
  const trigger = wrapper.querySelector('#dashboard-date-trigger');
  const value = wrapper.querySelector('#dashboard-date-value');
  const panel = wrapper.querySelector('#dashboard-calendar');
  const heading = panel.querySelector('[data-calendar-month]');
  const days = panel.querySelector('[data-calendar-days]');
  const monthSelect = panel.querySelector('[data-calendar-month-select]');
  const yearInput = panel.querySelector('[data-calendar-year-input]');
  const minimum = new Date(2026, 0, 1, 12);
  const clamp = date => date < minimum ? new Date(minimum) : date;
  const monthFormat = new Intl.DateTimeFormat('es-AR', { month: 'long', year: 'numeric' });
  const fullFormat = new Intl.DateTimeFormat('es-AR', { dateStyle: 'full' });
  const shortFormat = new Intl.DateTimeFormat('es-AR');
  const iso = date => date.getFullYear() + '-' + String(date.getMonth() + 1).padStart(2, '0') + '-' + String(date.getDate()).padStart(2, '0');
  const parse = text => { const [year, month, day] = text.split('-').map(Number); return new Date(year, month - 1, day, 12); };
  let focused = clamp(new Date());
  let month = new Date(focused.getFullYear(), focused.getMonth(), 1, 12);
  function sync() { value.textContent = input.value ? shortFormat.format(parse(input.value)) : 'Todas las fechas'; }
  function close(returnFocus = false) {
    panel.hidden = true;
    wrapper.classList.remove('is-open');
    trigger.setAttribute('aria-expanded', 'false');
    form.classList.remove('is-calendar-open');
    if (returnFocus) trigger.focus();
  }
  function choose(date) {
    if (date && date < minimum) return;
    input.value = date ? iso(date) : '';
    sync();
    close(true);
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }
  function draw(focusDay = false) {
    heading.textContent = monthFormat.format(month);
    monthSelect.value = String(month.getMonth());
    yearInput.value = String(month.getFullYear());
    const previous = panel.querySelector('[data-calendar-prev]');
    const atMinimum = month.getFullYear() === 2026 && month.getMonth() === 0;
    // Pasar el foco antes de desactivar la flecha evita que el popup se cierre.
    if (atMinimum && document.activeElement === previous) {
      panel.querySelector('[data-calendar-next]').focus({ preventScroll: true });
    }
    previous.disabled = atMinimum;
    days.replaceChildren();
    const offset = (month.getDay() + 6) % 7;
    const count = Math.ceil((offset + new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate()) / 7) * 7;
    const today = iso(new Date());
    let activeButton;
    for (let index = 0; index < count; index++) {
      const date = new Date(month.getFullYear(), month.getMonth(), 1 - offset + index, 12);
      const key = iso(date);
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = date.getDate();
      button.dataset.date = key;
      button.disabled = date < minimum;
      button.setAttribute('aria-label', fullFormat.format(date));
      button.setAttribute('aria-pressed', String(input.value === key));
      button.tabIndex = key === iso(focused) ? 0 : -1;
      if (key === today) button.setAttribute('aria-current', 'date');
      if (date.getMonth() !== month.getMonth()) button.className = 'is-outside';
      if (button.tabIndex === 0) activeButton = button;
      button.addEventListener('focus', () => { focused = date; });
      button.addEventListener('click', () => choose(date));
      days.append(button);
    }
    if (focusDay && activeButton) activeButton.focus();
  }
  function open() {
    focused = clamp(input.value ? parse(input.value) : new Date());
    month = new Date(focused.getFullYear(), focused.getMonth(), 1, 12);
    panel.hidden = false;
    wrapper.classList.add('is-open');
    form.classList.add('is-calendar-open');
    trigger.setAttribute('aria-expanded', 'true');
    draw(true);
  }
  function moveMonth(delta, focusDay = false) {
    const nextMonth = new Date(month.getFullYear(), month.getMonth() + delta, 1, 12);
    if (nextMonth < minimum) return;
    // En dispositivos táctiles el clic no siempre enfoca la flecha. Mantener
    // el foco dentro del panel al reemplazar los días del mes anterior.
    if (!focusDay) {
      panel.querySelector(delta < 0 ? '[data-calendar-prev]' : '[data-calendar-next]')
        .focus({ preventScroll: true });
    }
    month = nextMonth;
    focused = new Date(month.getFullYear(), month.getMonth(), Math.min(focused.getDate(), new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate()), 12);
    draw(focusDay);
  }
  function jumpToMonth() {
    const year = Number(yearInput.value);
    const selectedMonth = Number(monthSelect.value);
    if (!Number.isInteger(year) || year < 2026 || year > 9999 || !Number.isInteger(selectedMonth)) {
      draw();
      return;
    }
    month = new Date(year, selectedMonth, 1, 12);
    focused = new Date(year, selectedMonth, Math.min(focused.getDate(), new Date(year, selectedMonth + 1, 0).getDate()), 12);
    draw();
  }
  trigger.addEventListener('click', () => panel.hidden ? open() : close());
  panel.querySelector('[data-calendar-prev]').addEventListener('click', () => moveMonth(-1));
  panel.querySelector('[data-calendar-next]').addEventListener('click', () => moveMonth(1));
  monthSelect.addEventListener('change', jumpToMonth);
  yearInput.addEventListener('change', jumpToMonth);
  yearInput.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); jumpToMonth(); }
  });
  panel.querySelector('[data-calendar-today]').addEventListener('click', () => choose(new Date()));
  panel.querySelector('[data-calendar-clear]').addEventListener('click', () => choose(null));
  days.addEventListener('keydown', event => {
    const deltas = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
    if (event.key in deltas || event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      const weekday = (focused.getDay() + 6) % 7;
      const delta = event.key === 'Home' ? -weekday : event.key === 'End' ? 6 - weekday : deltas[event.key];
      focused = clamp(new Date(focused.getFullYear(), focused.getMonth(), focused.getDate() + delta, 12));
      month = new Date(focused.getFullYear(), focused.getMonth(), 1, 12);
      draw(true);
    } else if (event.key === 'PageUp' || event.key === 'PageDown') {
      event.preventDefault();
      moveMonth(event.key === 'PageUp' ? -1 : 1, true);
    }
  });
  wrapper.addEventListener('keydown', event => { if (event.key === 'Escape' && !panel.hidden) { event.preventDefault(); close(true); } });
  // No cerrar por clic o foco fuera del panel: al reconstruir los días del mes,
  // algunos navegadores informan transitoriamente que el foco salió del calendario.
  // El botón principal, Escape y la elección de una fecha sí lo cierran.
  form.addEventListener('reset', () => { close(); setTimeout(sync, 0); });
  input.addEventListener('change', sync);
  sync();
})();
