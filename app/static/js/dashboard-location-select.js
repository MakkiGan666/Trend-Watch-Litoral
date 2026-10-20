(function () {
  'use strict';
  function enhanceSelect(select) {
    const form = select.closest('form');
    const label = form.querySelector('label[for="' + select.id + '"]');
    const prefix = select.id;
    const wrapper = document.createElement('div');
    wrapper.className = 'dashboard-location-select';
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.id = prefix + '-trigger';
    trigger.className = 'select dashboard-location-select__trigger';
    trigger.setAttribute('role', 'combobox');
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.setAttribute('aria-controls', prefix + '-options');
    trigger.setAttribute('aria-autocomplete', 'none');
    label.id = prefix + '-label';
    trigger.setAttribute('aria-labelledby', label.id + ' ' + prefix + '-value');
    const value = document.createElement('span');
    value.id = prefix + '-value';
    trigger.append(value);
    const menu = document.createElement('div');
    menu.id = prefix + '-options';
    menu.className = 'dashboard-location-select__menu';
    menu.setAttribute('role', 'listbox');
    menu.setAttribute('aria-labelledby', label.id);
    menu.hidden = true;
    let active = 0;
    let typed = '';
    let lastTyped = 0;
    const normalize = text => text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
    const items = Array.from(select.options).map((option, index) => {
      const item = document.createElement('div');
      item.id = prefix + '-option-' + index;
      item.className = 'dashboard-location-select__option';
      item.setAttribute('role', 'option');
      item.textContent = option.textContent;
      item.addEventListener('mousedown', event => event.preventDefault());
      item.addEventListener('click', () => choose(index));
      menu.append(item);
      return item;
    });
    function sync() {
      active = Math.max(0, select.selectedIndex);
      value.textContent = select.options[active].textContent;
      items.forEach((item, index) => item.setAttribute('aria-selected', String(index === active)));
      highlight(active);
    }
    function highlight(index) {
      active = (index + items.length) % items.length;
      items.forEach((item, i) => item.classList.toggle('is-active', i === active));
      if (!menu.hidden) {
        trigger.setAttribute('aria-activedescendant', items[active].id);
        items[active].scrollIntoView({ block: 'nearest' });
      }
    }
    function close() {
      menu.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
      trigger.removeAttribute('aria-activedescendant');
      if (!form.querySelector('.dashboard-location-select__trigger[aria-expanded="true"]')) form.classList.remove('is-location-open');
      typed = '';
    }
    function open() {
      sync();
      menu.hidden = false;
      menu.style.maxHeight = Math.min(320, Math.max(80, window.innerHeight - trigger.getBoundingClientRect().bottom - 20)) + 'px';
      form.classList.add('is-location-open');
      trigger.setAttribute('aria-expanded', 'true');
      highlight(active);
    }
    function choose(index) {
      select.selectedIndex = index;
      sync();
      close();
      trigger.focus();
      select.dispatchEvent(new Event('change', { bubbles: true }));
    }
    trigger.addEventListener('click', () => menu.hidden ? open() : close());
    trigger.addEventListener('keydown', event => {
      if (['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', ' '].includes(event.key)) {
        event.preventDefault();
        if (menu.hidden) {
          open();
          if (event.key === 'Home') highlight(0);
          if (event.key === 'End') highlight(items.length - 1);
        } else if (event.key === 'Enter' || event.key === ' ') choose(active);
        else highlight(event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : active + (event.key === 'ArrowDown' ? 1 : -1));
      } else if (event.key === 'Escape') {
        if (!menu.hidden) event.preventDefault();
        close();
      } else if (event.key === 'Tab') close();
      else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        if (menu.hidden) open();
        const now = Date.now();
        typed = now - lastTyped > 700 ? event.key : typed + event.key;
        lastTyped = now;
        const found = items.findIndex(item => normalize(item.textContent).startsWith(normalize(typed)));
        if (found >= 0) highlight(found);
      }
    });
    document.addEventListener('click', event => { if (!wrapper.contains(event.target)) close(); });
    wrapper.addEventListener('focusout', event => { if (!wrapper.contains(event.relatedTarget)) close(); });
    window.addEventListener('resize', close);
    select.addEventListener('change', sync);
    form.addEventListener('reset', () => { close(); setTimeout(sync, 0); });
    select.before(wrapper);
    wrapper.append(select, trigger, menu);
    select.hidden = true;
    label.htmlFor = trigger.id;
    sync();
  }
  document.querySelectorAll('#dashboard-location, #dashboard-source, #dashboard-category').forEach(enhanceSelect);
})();
