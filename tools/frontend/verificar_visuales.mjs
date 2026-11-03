// Fixtures rendered from the real templates; see the validation report for setup.
// node --experimental-websocket tools/frontend/verificar_visuales.mjs PORT BASE_URL OUTPUT_DIR
import fs from 'node:fs';
import assert from 'node:assert/strict';
const [port, base, output] = process.argv.slice(2);
const ws = new WebSocket(`ws://127.0.0.1:${port}/session`);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
let id = 0;
const pending = new Map();
ws.onmessage = event => {
  const message = JSON.parse(event.data);
  if (!message.id) return;
  const task = pending.get(message.id);
  if (!task) return;
  pending.delete(message.id);
  if (message.type === 'error') task.reject(Error(JSON.stringify(message)));
  else task.resolve(message.result);
};
function call(method, params = {}) {
  return new Promise((resolve, reject) => {
    const current = ++id;
    pending.set(current, { resolve, reject });
    ws.send(JSON.stringify({ id: current, method, params }));
    setTimeout(() => {
      if (pending.delete(current)) reject(Error(`${method}: timeout`));
    }, 15000).unref();
  });
}
await call('session.new', { capabilities: { alwaysMatch: {} } });
const { context } = await call('browsingContext.create', { type: 'tab' });
async function evaluate(expression) {
  const result = await call('script.evaluate', {
    target: { context }, expression: `JSON.stringify((${expression}))`, awaitPromise: true,
  });
  if (result.type === 'exception') throw Error(JSON.stringify(result.exceptionDetails));
  return JSON.parse(result.result.value);
}
async function navigate(file) {
  await call('browsingContext.navigate', { context, url: `${base}/${file}.html`, wait: 'complete' });
}
async function key(value) {
  await call('input.performActions', { context, actions: [{ type: 'key', id: 'keyboard', actions: [
    { type: 'keyDown', value }, { type: 'keyUp', value },
  ] }] });
}
async function shot(name) {
  const result = await call('browsingContext.captureScreenshot', { context });
  fs.writeFileSync(`${output}/${name}.png`, Buffer.from(result.data, 'base64'));
}
const checks = [];
const measurements = [];
function check(name, value) { assert.ok(value, name); checks.push(name); }
async function stableCalendar(selector, label) {
  let reference;
  for (const [year, month] of [[2026, 10], [2026, 11], [2027, 1], [2028, 1]]) {
    const geometry = await evaluate(`(()=>{
      const p=document.querySelector('${selector}');
      p.querySelector('[data-calendar-year-input]').value='${year}';
      p.querySelector('[data-calendar-month-select]').value='${month}';
      p.querySelector('[data-calendar-month-select]').dispatchEvent(new Event('change'));
      const cells=[...p.querySelectorAll('[data-calendar-days] button')];
      const r=p.getBoundingClientRect();
      return {width:r.width,height:r.height,count:cells.length,
        rows:new Set(cells.map(c=>Math.round(c.getBoundingClientRect().top))).size,
        columns:new Set(cells.map(c=>Math.round(c.getBoundingClientRect().left))).size,
        outside:cells.filter(c=>c.classList.contains('is-outside')).length};
    })()`);
    reference ??= geometry;
    check(`grilla 6x7 y relleno ${label} ${year}-${month+1}`, geometry.count === 42 && geometry.rows === 6 && geometry.columns === 7 && geometry.outside > 0);
    check(`panel estable ${label} ${year}-${month+1}`, Math.abs(reference.width-geometry.width)<1 && Math.abs(reference.height-geometry.height)<1);
    measurements.push({ calendar: label, year, month: month+1, ...geometry });
  }
  await evaluate(`document.querySelector('${selector} [data-date="2028-02-29"]').click(),true`);
  check(`seleccion bisiesto ${label}`, await evaluate(`document.querySelector('${selector}').closest('[data-dashboard-calendar]').querySelector('input[name]').value==='2028-02-29'`));
  await evaluate(`document.querySelector('${selector}').closest('[data-dashboard-calendar]').querySelector('.dashboard-date__trigger').click(),true`);
  await evaluate(`document.querySelector('${selector} [data-calendar-today]').click(),true`);
  check(`Hoy ${label}`, await evaluate(`(()=>{const d=new Date();const iso=d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');return document.querySelector('${selector}').closest('[data-dashboard-calendar]').querySelector('input[name]').value===iso})()`));
  await evaluate(`document.querySelector('${selector}').closest('[data-dashboard-calendar]').querySelector('.dashboard-date__trigger').click(),true`);
  await evaluate(`document.querySelector('${selector} [data-calendar-clear]').click(),true`);
  check(`Quitar fecha ${label}`, await evaluate(`document.querySelector('${selector}').closest('[data-dashboard-calendar]').querySelector('input[name]').value===''`));
}
try {
  await navigate('dashboard');
  check('persistencia inicial ISO', await evaluate(`document.querySelector('[name=desde]').value==='2026-10-01' && document.querySelector('[name=hasta]').value==='2026-10-31'`));
  await evaluate(`document.querySelector('#id_desde-trigger').click(),true`);
  check('apertura y foco', await evaluate(`document.activeElement.dataset.date==='2026-10-01'`));
  await key('\uE014');
  check('flecha derecha', await evaluate(`document.activeElement.dataset.date==='2026-10-02'`));
  await key('\uE007');
  check('seleccion teclado y retorno de foco', await evaluate(`document.querySelector('[name=desde]').value==='2026-10-02' && document.activeElement.id==='id_desde-trigger'`));
  await evaluate(`document.querySelector('#id_hasta-trigger').click(),true`);
  await key('\uE00C');
  check('Escape', await evaluate(`document.querySelector('#id_hasta-calendar').hidden && document.activeElement.id==='id_hasta-trigger'`));
  await evaluate(`document.querySelector('#id_desde-trigger').click(),true`);
  await evaluate(`document.querySelector('#id_desde-calendar [data-calendar-prev]').click(),true`);
  check('mes anterior', await evaluate(`document.querySelector('#id_desde-calendar [data-calendar-month-select]').value==='8'`));
  await evaluate(`(()=>{const p=document.querySelector('#id_desde-calendar');p.querySelector('[data-calendar-year-input]').value='2024';p.querySelector('[data-calendar-month-select]').value='1';p.querySelector('[data-calendar-year-input]').dispatchEvent(new Event('change'));return true})()`);
  check('salto de año y bisiesto', await evaluate(`!!document.querySelector('#id_desde-calendar [data-date="2024-02-29"]')`));
  await evaluate(`document.querySelector('#id_desde-calendar [data-date="2024-02-29"]').click(),true`);
  await evaluate(`document.querySelector('#id_hasta-trigger').click(),true`);
  await key('\uE00E');
  check('PageUp ajusta el dia al mes', await evaluate(`document.activeElement.dataset.date==='2026-09-30'`));
  await key('\uE011');
  check('Home al lunes', await evaluate(`document.activeElement.dataset.date==='2026-09-28'`));
  await key('\uE010');
  check('End al domingo', await evaluate(`document.activeElement.dataset.date==='2026-10-04'`));
  await evaluate(`(()=>{const y=document.querySelector('#id_hasta-calendar [data-calendar-year-input]');y.value='0';y.dispatchEvent(new Event('change'));return true})()`);
  check('año invalido se rechaza', await evaluate(`document.querySelector('#id_hasta-calendar [data-calendar-year-input]').value==='2026'`));
  await evaluate(`document.querySelector('#id_hasta-calendar [data-calendar-clear]').click(),true`);
  check('quitar fecha independiente', await evaluate(`document.querySelector('[name=hasta]').value==='' && document.querySelector('[name=desde]').value==='2024-02-29'`));
  await evaluate(`document.querySelector('.analytics-filters button[type=submit]').click(),true`);
  await new Promise(resolve => setTimeout(resolve, 200));
  check('envio GET sin autoenvio', await evaluate(`new URL(location.href).searchParams.get('desde')==='2024-02-29' && new URL(location.href).searchParams.get('hasta')===''`));
  await navigate('dashboard-nojs');
  check('respaldo nativo sin JS', await evaluate(`!document.querySelector('[name=desde]').hidden && document.querySelector('[name=desde]').type==='date' && document.querySelector('#id_desde-trigger').hidden`));
  await navigate('publicaciones');
  await evaluate(`document.querySelector('#dashboard-date-trigger').click(),true`);
  check('Publicaciones mantiene fecha y minimo', await evaluate(`document.activeElement.dataset.date==='2026-01-15' && document.querySelector('[data-calendar-prev]').disabled`));
  await evaluate(`document.querySelector('[data-dashboard-filters]').addEventListener('submit',event=>event.preventDefault()),true`);
  await stableCalendar('#dashboard-calendar', 'Publicaciones');
  for (const width of [320, 375, 768, 1024, 1440]) {
    await call('browsingContext.setViewport', { context, viewport: { width, height: 900 } });
    await navigate('dashboard');
    for (const field of ['desde', 'hasta']) {
      await evaluate(`document.querySelector('#id_${field}-trigger').click(),true`);
      check(`calendario dentro del viewport ${field} ${width}`, await evaluate(`(()=>{const r=document.querySelector('#id_${field}-calendar').getBoundingClientRect();return r.left>=0 && r.right<=innerWidth && r.width>0 && document.documentElement.scrollWidth<=innerWidth})()`));
      await stableCalendar(`#id_${field}-calendar`, `${field} ${width}`);
      await evaluate(`document.querySelector('#id_${field}-trigger').click(),true`);
    }
    await shot(`dashboard-${width}`);
    let reference;
    for (const variant of ['vertical', 'horizontal', 'pequena', 'ausente', 'fallida']) {
      await navigate(variant);
      const geometry = await evaluate(`(()=>{const r=document.querySelector('[data-news-reading]').getBoundingClientRect();const title=document.querySelector('.news-detail h1').getBoundingClientRect();const text=document.querySelector('[data-news-content] p').getBoundingClientRect();return {width:r.width,left:r.left,titleLeft:title.left,textLeft:text.left,overflow:document.documentElement.scrollWidth>innerWidth}})()`);
      measurements.push({ viewport: width, variant, ...geometry });
      reference ??= geometry.width;
      check(`texto alineado con titulo ${variant} ${width}`, Math.abs(geometry.titleLeft-geometry.textLeft)<1 && Math.abs(geometry.left-geometry.titleLeft)<1);
      check(`ancho independiente ${variant} ${width}`, Math.abs(reference - geometry.width) < 1 && !geometry.overflow);
      await evaluate(`document.querySelector('[data-news-read-more]').click(),true`);
      check(`Leer mas ${variant} ${width}`, await evaluate(`!document.querySelector('[data-news-reading]').classList.contains('is-collapsed')`));
      await evaluate(`document.querySelector('[data-news-read-more]').click(),true`);
      check(`Leer menos ${variant} ${width}`, await evaluate(`document.querySelector('[data-news-reading]').classList.contains('is-collapsed')`));
      if (variant === 'vertical') {
        await evaluate(`document.querySelector('[data-news-reading]').scrollIntoView({block:'center',behavior:'instant'}),true`);
        await shot(`noticia-${width}`);
      }
    }
  }
  fs.writeFileSync(`${output}/browser-results.json`, JSON.stringify({ checks, measurements }, null, 2));
  console.log(`PASS: ${checks.length} comprobaciones; capturas en ${output}`);
} finally {
  await call('session.end');
  ws.close();
}
