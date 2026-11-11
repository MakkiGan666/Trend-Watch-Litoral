(function () {
  'use strict';
  document.querySelectorAll('[data-dashboard-calendar]').forEach(initCalendar);

  function initCalendar(wrapper) {
    const form = wrapper.closest('form');
    const input = wrapper.querySelector('input[name]');
    const trigger = wrapper.querySelector('.dashboard-date__trigger');
    const value = trigger.querySelector('span');
    const panel = wrapper.querySelector('.dashboard-calendar');
    const heading = panel.querySelector('[data-calendar-month]');
    const days = panel.querySelector('[data-calendar-days]');
    const monthSelect = panel.querySelector('[data-calendar-month-select]');
    const yearInput = panel.querySelector('[data-calendar-year-input]');
    const nativeInput = input.type === 'date';
    const minimumYear = Number(yearInput.min) || 1;
    function makeDate(year, month, day) {
      const date = new Date(2000, 0, 1, 12);
      date.setFullYear(year, month, day);
      return date;
    }
    const minimum = makeDate(minimumYear, 0, 1);
    const maximumText = wrapper.dataset.calendarMaxDate;
    const maximum = maximumText
      ? makeDate(...maximumText.split('-').map((value, index) => Number(value) - (index === 1 ? 1 : 0)))
      : makeDate(9999, 11, 31);
    const maximumMonth = makeDate(maximum.getFullYear(), maximum.getMonth(), 1);
    yearInput.max = String(maximum.getFullYear());
    const clamp = date => new Date(Math.min(maximum, Math.max(minimum, date)));
    const monthFormat = new Intl.DateTimeFormat('es-AR', { month: 'long', year: 'numeric' });
    const fullFormat = new Intl.DateTimeFormat('es-AR', { dateStyle: 'full' });
    const shortFormat = new Intl.DateTimeFormat('es-AR');
    const iso = date => String(date.getFullYear()).padStart(4, '0') + '-' + String(date.getMonth() + 1).padStart(2, '0') + '-' + String(date.getDate()).padStart(2, '0');
    const parse = text => { const [year, month, day] = text.split('-').map(Number); return makeDate(year, month - 1, day); };
    let focused = clamp(new Date());
    let month = makeDate(focused.getFullYear(), focused.getMonth(), 1);
    function sync() { value.textContent = input.value ? shortFormat.format(parse(input.value)) : (nativeInput ? 'Sin límite' : 'Todas las fechas'); }
    function close(returnFocus = false) {
      panel.hidden = true;
      wrapper.classList.remove('is-open');
      trigger.setAttribute('aria-expanded', 'false');
      if (!form.querySelector('.dashboard-date.is-open')) form.classList.remove('is-calendar-open');
      if (returnFocus) trigger.focus();
    }
    function choose(date) {
      if (date && (date < minimum || date > maximum)) return;
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
      const atMinimum = month.getFullYear() === minimumYear && month.getMonth() === 0;
      const next = panel.querySelector('[data-calendar-next]');
      const atMaximum = month.getTime() >= maximumMonth.getTime();
      if (atMaximum && document.activeElement === next) previous.focus({ preventScroll: true });
      next.disabled = atMaximum;
      // Pasar el foco antes de desactivar la flecha evita que el popup se cierre.
      if (atMinimum && document.activeElement === previous) {
        panel.querySelector('[data-calendar-next]').focus({ preventScroll: true });
      }
      previous.disabled = atMinimum;
      for (const option of monthSelect.options) {
        option.disabled = month.getFullYear() === maximum.getFullYear() && Number(option.value) > maximum.getMonth();
      }
      days.replaceChildren();
      const offset = (month.getDay() + 6) % 7;
      // Seis semanas completas mantienen estable la altura al cambiar de mes.
      const count = 42;
      const today = iso(new Date());
      let activeButton;
      for (let index = 0; index < count; index++) {
        const date = makeDate(month.getFullYear(), month.getMonth(), 1 - offset + index);
        const key = iso(date);
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = date.getDate();
        button.dataset.date = key;
        button.disabled = date < minimum || date > maximum;
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
      document.querySelectorAll('[data-dashboard-calendar]').forEach(other => {
        if (other !== wrapper) other.dispatchEvent(new Event('calendar-close'));
      });
      focused = clamp(input.value ? parse(input.value) : new Date());
      month = makeDate(focused.getFullYear(), focused.getMonth(), 1);
      panel.hidden = false;
      wrapper.classList.add('is-open');
      form.classList.add('is-calendar-open');
      trigger.setAttribute('aria-expanded', 'true');
      draw(true);
      if (nativeInput) {
        const rect = wrapper.getBoundingClientRect();
        const width = panel.getBoundingClientRect().width;
        panel.style.left = Math.max(12 - rect.left, Math.min(0, window.innerWidth - 12 - rect.left - width)) + 'px';
      }
    }
    function moveMonth(delta, focusDay = false) {
      const nextMonth = makeDate(month.getFullYear(), month.getMonth() + delta, 1);
      if (nextMonth < minimum || nextMonth > maximumMonth) return;
      // En dispositivos táctiles el clic no siempre enfoca la flecha. Mantener
      // el foco dentro del panel al reemplazar los días del mes anterior.
      if (!focusDay) {
        panel.querySelector(delta < 0 ? '[data-calendar-prev]' : '[data-calendar-next]')
          .focus({ preventScroll: true });
      }
      month = nextMonth;
      focused = clamp(makeDate(month.getFullYear(), month.getMonth(), Math.min(focused.getDate(), makeDate(month.getFullYear(), month.getMonth() + 1, 0).getDate())));
      draw(focusDay);
    }
    function jumpToMonth() {
      const year = Number(yearInput.value);
      const selectedMonth = Number(monthSelect.value);
      if (!Number.isInteger(year) || year < minimumYear || year > 9999 || !Number.isInteger(selectedMonth)) {
        draw();
        return;
      }
      const requestedMonth = makeDate(year, selectedMonth, 1);
      month = requestedMonth > maximumMonth ? new Date(maximumMonth) : requestedMonth;
      focused = clamp(makeDate(month.getFullYear(), month.getMonth(), Math.min(focused.getDate(), makeDate(month.getFullYear(), month.getMonth() + 1, 0).getDate())));
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
    panel.querySelector('[data-calendar-today]').addEventListener('click', () => choose(clamp(new Date())));
    panel.querySelector('[data-calendar-clear]').addEventListener('click', () => choose(null));
    days.addEventListener('keydown', event => {
      const deltas = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
      if (event.key in deltas || event.key === 'Home' || event.key === 'End') {
        event.preventDefault();
        const weekday = (focused.getDay() + 6) % 7;
        const delta = event.key === 'Home' ? -weekday : event.key === 'End' ? 6 - weekday : deltas[event.key];
        focused = clamp(makeDate(focused.getFullYear(), focused.getMonth(), focused.getDate() + delta));
        month = makeDate(focused.getFullYear(), focused.getMonth(), 1);
        draw(true);
      } else if (event.key === 'PageUp' || event.key === 'PageDown') {
        event.preventDefault();
        moveMonth(event.key === 'PageUp' ? -1 : 1, true);
      }
    });
    wrapper.addEventListener('keydown', event => { if (event.key === 'Escape' && !panel.hidden) { event.preventDefault(); close(true); } });
    // Publicaciones conserva su cierre explícito para no cambiar el autoenvío existente.
    // Los inputs mejorados también cierran al salir, comprobando el foco tras redibujar.
    wrapper.addEventListener('calendar-close', () => close());
    form.addEventListener('reset', () => { close(); setTimeout(sync, 0); });
    input.addEventListener('change', sync);
    sync();
    if (nativeInput) {
      input.hidden = true;
      trigger.hidden = false;
      wrapper.querySelector('label').htmlFor = trigger.id;
      window.addEventListener('resize', () => close());
      document.addEventListener('pointerdown', event => {
        if (!wrapper.contains(event.target)) close();
      });
      wrapper.addEventListener('focusout', () => {
        setTimeout(() => { if (!wrapper.contains(document.activeElement)) close(); }, 0);
      });
    }
  }
})();
