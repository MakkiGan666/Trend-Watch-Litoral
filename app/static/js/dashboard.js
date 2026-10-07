(function () {
  'use strict';
  const page = document.querySelector('[data-dashboard]');
  if (!page) return;
  const form = page.querySelector('[data-dashboard-filters]');
  const rows = Array.from(page.querySelectorAll('[data-dashboard-row]'));
  const search = page.querySelector('#dashboard-search');
  const source = page.querySelector('#dashboard-source');
  const location = page.querySelector('#dashboard-location');
  const analysis = page.querySelector('#dashboard-analysis');
  const normalize = value => String(value).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  const records = rows.map(row => ({
    row,
    text: normalize(row.textContent),
    source: row.dataset.source,
    locations: Array.from(row.querySelectorAll('[data-location]')).map(el => el.dataset.location),
    analysis: row.dataset.analysis
  }));
  function options(select, values) {
    Array.from(new Set(values)).sort((a, b) => a.localeCompare(b, 'es')).forEach(value => {
      const option = document.createElement('option');
      option.value = option.textContent = value;
      select.append(option);
    });
  }
  options(source, records.map(record => record.source));
  options(location, records.flatMap(record => record.locations));
  function render() {
    const query = normalize(search.value);
    let total = 0;
    let analyzed = 0;
    records.forEach(record => {
      const locationMatches = !location.value || (location.value === '__missing'
        ? !record.locations.length : record.locations.includes(location.value));
      const visible = record.text.includes(query) && (!source.value || record.source === source.value)
        && locationMatches && (!analysis.value || record.analysis === analysis.value);
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
  form.addEventListener('submit', event => event.preventDefault());
  form.addEventListener('input', render);
  form.addEventListener('change', render);
  form.addEventListener('reset', () => setTimeout(render, 0));
  form.hidden = false;
  page.querySelector('[data-dashboard-summary]').hidden = false;
  render();
})();
