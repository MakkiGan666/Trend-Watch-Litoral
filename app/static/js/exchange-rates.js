(function () {
  'use strict';
  const panel = document.querySelector('[data-exchange-rates]');
  if (!panel) return;
  const status = panel.querySelector('[data-exchange-status]');
  const retry = panel.querySelector('[data-exchange-retry]');
  const rows = Array.from(panel.querySelectorAll('[data-currency]'));
  const money = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const dateFormat = new Intl.DateTimeFormat('es-AR', { dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Argentina/Buenos_Aires' });
  let busy = false;
  let lastCheck = 0;
  function render(payload) {
    let available = 0;
    let stale = false;
    rows.forEach(row => {
      const rate = payload.data.find(item => item.key === row.dataset.currency);
      const valid = rate && typeof rate.compra === 'number' && typeof rate.venta === 'number'
        && Number.isFinite(rate.compra) && Number.isFinite(rate.venta) && rate.compra > 0 && rate.venta > 0;
      row.querySelector('[data-buy]').textContent = valid ? money.format(rate.compra) : '—';
      row.querySelector('[data-sell]').textContent = valid ? money.format(rate.venta) : '—';
      const updated = valid ? new Date(rate.fechaActualizacion) : null;
      const date = updated && Number.isFinite(updated.getTime()) ? dateFormat.format(updated) + ' · Argentina' : 'Fecha no disponible';
      row.querySelector('[data-rate-date]').textContent = valid
        ? (rate.stale ? 'Último dato disponible: ' : 'Actualizado: ') + date
        : 'Cotización no disponible.';
      if (valid) available++;
      if (valid && rate.stale) stale = true;
    });
    status.textContent = available === rows.length && !stale ? 'Valores publicados por la fuente.'
      : (available ? 'Algunos valores no pudieron actualizarse.' : 'No pudimos consultar las cotizaciones.');
    retry.hidden = available === rows.length && !stale;
  }
  async function load() {
    if (busy) return;
    busy = true;
    panel.setAttribute('aria-busy', 'true');
    retry.disabled = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(panel.dataset.exchangeRates, { headers: { Accept: 'application/json' }, signal: controller.signal });
      const payload = await response.json();
      if (!response.ok || !Array.isArray(payload.data)) throw new Error('Cotizaciones no disponibles');
      render(payload);
    } catch (_) {
      status.textContent = 'No pudimos actualizar las cotizaciones. Los valores visibles conservan su fecha original.';
      retry.hidden = false;
    } finally {
      clearTimeout(timeout);
      lastCheck = Date.now();
      busy = false;
      retry.disabled = false;
      panel.setAttribute('aria-busy', 'false');
    }
  }
  retry.addEventListener('click', load);
  setInterval(() => { if (document.visibilityState === 'visible') load(); }, 300000);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && Date.now() - lastCheck >= 300000) load();
  });
  load();
})();
