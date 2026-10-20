(function () {
  'use strict';
  const page = document.querySelector('[data-dashboard]');
  if (!page) return;
  const form = page.querySelector('[data-dashboard-filters]');
  const rows = Array.from(page.querySelectorAll('[data-dashboard-row]'));
  const search = page.querySelector('#dashboard-search');
  const source = page.querySelector('#dashboard-source');
  const location = page.querySelector('#dashboard-location');
  const category = page.querySelector('#dashboard-category');
  const date = page.querySelector('#dashboard-date');
  const editToggle = page.querySelector('[data-dashboard-edit-toggle]');
  const editHelp = page.querySelector('[data-dashboard-edit-help]');
  let editing = false;
  function setEditing(value) {
    editing = value;
    page.querySelectorAll('[data-dashboard-actions]').forEach(cell => { cell.hidden = !editing; });
    page.querySelectorAll('[data-dashboard-empty-cell]').forEach(cell => { cell.colSpan = editing ? 7 : 6; });
    editToggle.setAttribute('aria-pressed', String(editing));
    editToggle.textContent = editing ? 'Finalizar edición' : 'Editar publicación';
    editHelp.hidden = !editing;
  }
  if (editToggle) {
    setEditing(false);
    editToggle.hidden = false;
    editToggle.addEventListener('click', () => setEditing(!editing));
  }
  const normalize = value => String(value).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  const sourceName = value => {
    const original = String(value || '').trim();
    return /^el\s+territorio(?:\s*\([^)]*\))?$/i.test(original) ? 'El Territorio' : original;
  };
  const records = rows.map(row => ({
    row,
    text: normalize(Array.from(row.cells)
      .filter(cell => !cell.hasAttribute('data-dashboard-actions'))
      .map(cell => cell.textContent).join(' ')),
    source: sourceName(row.dataset.source),
    locations: (row.dataset.departamentos || '').split(',').filter(Boolean),
    categories: (row.dataset.categories || '').split(',').filter(Boolean),
    analysis: row.dataset.analysis,
    captureDate: row.dataset.captureDate || ''
  }));
  function options(select, values) {
    Array.from(new Set(values)).sort((a, b) => a.localeCompare(b, 'es')).forEach(value => {
      const option = document.createElement('option');
      option.value = option.textContent = value;
      select.append(option);
    });
  }
  options(source, records.map(record => record.source));
  function render() {
    const query = normalize(search.value);
    let total = 0;
    let analyzed = 0;
    records.forEach(record => {
      const locationMatches = !location.value || (location.value === '__missing'
        ? !record.locations.length : record.locations.includes(location.value));
      const categoryMatches = !category.value || (category.value === '__missing'
        ? !record.categories.length : record.categories.includes(category.value));
      const visible = record.text.includes(query) && (!source.value || record.source === source.value)
        && locationMatches && categoryMatches
        && (!date || !date.value || record.captureDate === date.value);
      record.row.hidden = !visible;
      if (visible) {
        total++;
        if (record.analysis === 'available') analyzed++;
      }
    });
    page.querySelector('[data-dashboard-total]').textContent = total;
    page.querySelector('[data-dashboard-analyzed]').textContent = analyzed;
    page.querySelector('[data-dashboard-pending]').textContent = total - analyzed;
    page.querySelector('[data-dashboard-count]').textContent = total + ' de ' + records.length + ' registros';
    page.querySelector('[data-dashboard-empty]').hidden = total > 0 || records.length === 0;
  }
  page.querySelectorAll('form[data-confirm]').forEach(deleteForm => {
    deleteForm.addEventListener('submit', event => {
      if (!editing) { event.preventDefault(); return; }
      if (!window.confirm(deleteForm.dataset.confirm)) event.preventDefault();
    });
  });
  form.addEventListener('submit', event => event.preventDefault());
  form.addEventListener('input', render);
  form.addEventListener('change', render);
  form.addEventListener('reset', () => setTimeout(render, 0));
  form.hidden = false;
  page.querySelector('[data-dashboard-summary]').hidden = false;
  render();
})();
