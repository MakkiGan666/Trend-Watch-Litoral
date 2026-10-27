// Prueba de DOM con jsdom como herramienta de desarrollo, no dependencia del sitio.
// NODE_PATH=/ruta/a/node_modules node --test tools/buscador/test_autocompletado.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { JSDOM } = require('jsdom');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../app/static/js/news-search.js'), 'utf8');
function setup() {
  const dom = new JSDOM('<form data-suggestions-url="/api/publicaciones/sugerencias/"><input id="q" name="q"><button>Buscar</button></form>', { url: 'http://localhost/', runScripts: 'outside-only' });
  const requests = [], timers = new Map(); let id = 0;
  const win = dom.window;
  win.fetch = (url, options) => new Promise(resolve => requests.push({ url: String(url), options, resolve }));
  win.setTimeout = (fn, ms) => { timers.set(++id, {fn, ms}); return id; };
  win.clearTimeout = id => timers.delete(id);
  win.HTMLElement.prototype.scrollIntoView = () => {};
  win.eval(source);
  const input = win.document.querySelector('input'), form = input.form;
  let submissions = 0; form.requestSubmit = () => submissions++;
  const change = value => { input.value = value; input.dispatchEvent(new win.Event('input')); };
  const tick = () => { for (const [id, timer] of [...timers]) if (timer.ms === 300) { timers.delete(id); timer.fn(); } };
  const key = key => { const e = new win.KeyboardEvent('keydown', {key, bubbles:true, cancelable:true}); input.dispatchEvent(e); return e; };
  const data = title => ({ terminos:[{texto:title,consulta:title}], noticias:[{titulo:'Noticia '+title,url:'/noticia/1/'}] });
  const respond = async (index, body, ok=true) => { requests[index].resolve({ok, json:async()=>body}); await new Promise(setImmediate); };
  return { win, input, form, requests, timers, change, tick, key, data, respond, submissions:()=>submissions };
}
test('mínimo, debounce y cancelación', async () => {
 const s=setup();s.change('m');s.tick();assert.equal(s.requests.length,0);
 s.change('mi');s.change('mis');assert.equal([...s.timers.values()].filter(t=>t.ms===300).length,1);
 s.tick();assert.equal(s.requests.length,1);assert.match(s.requests[0].url,/q=mis/);
 s.change('mini');assert.equal(s.requests[0].options.signal.aborted,true);s.tick();
 await s.respond(1,s.data('Ministerio'));await s.respond(0,s.data('Misiones'));
 assert.match(s.form.textContent,/Ministerio/);assert.doesNotMatch(s.form.textContent,/Misiones/);
 s.change('');assert.equal(s.form.querySelector('[role=listbox]').hidden,true);
});
test('teclado, Enter sin selección y Escape', async () => {
 const s=setup();s.change('mi');s.tick();await s.respond(0,s.data('Misiones'));
 assert.equal(s.key('Enter').defaultPrevented,false);
 s.key('ArrowDown');assert.match(s.input.getAttribute('aria-activedescendant'),/-0$/);
 s.key('Enter');assert.equal(s.submissions(),1);assert.equal(s.input.value,'Misiones');
 s.change('mi');s.tick();await s.respond(1,s.data('Minería'));
 assert.equal(s.key('Escape').defaultPrevented,true);assert.equal(s.input.getAttribute('aria-expanded'),'false');
 assert.equal(s.key('Escape').defaultPrevented,false);
});
test('clic/toque, texto seguro, vacío y errores', async () => {
 const s=setup();s.change('mi');s.tick();await s.respond(0,s.data('<img onerror=alert(1)>'));
 assert.equal(s.form.querySelector('img'),null);
 s.form.querySelector('[role=option]').dispatchEvent(new s.win.MouseEvent('click',{bubbles:true,cancelable:true,button:0}));
 assert.equal(s.submissions(),1);
 s.change('mi');s.tick();await s.respond(1,{terminos:[],noticias:[]});assert.equal(s.input.getAttribute('aria-expanded'),'false');
 s.change('mi');s.tick();await s.respond(2,{},false);assert.equal(s.input.getAttribute('aria-expanded'),'false');
 assert.equal(s.key('Enter').defaultPrevented,false);
});
test('flechas hacia arriba y composición IME', async () => {
 const s=setup();s.input.dispatchEvent(new s.win.Event('compositionstart'));s.change('mi');s.tick();assert.equal(s.requests.length,0);
 s.input.dispatchEvent(new s.win.Event('compositionend'));s.tick();await s.respond(0,s.data('Misiones'));
 s.key('ArrowUp');assert.match(s.input.getAttribute('aria-activedescendant'),/-1$/);
 s.key('ArrowDown');assert.match(s.input.getAttribute('aria-activedescendant'),/-0$/);
 s.input.dispatchEvent(new s.win.Event('blur'));assert.equal(s.input.getAttribute('aria-expanded'),'false');
});

test('toque selecciona al soltar; arrastrar/cancelar no selecciona', async () => {
 const s=setup();s.change('mi');s.tick();await s.respond(0,s.data('Misiones'));
 const option=s.form.querySelector('[role=option]');
 const pointer=(type,x,y)=>{const e=new s.win.MouseEvent(type,{bubbles:true,cancelable:true,button:0,clientX:x,clientY:y});Object.defineProperties(e,{pointerType:{value:'touch'},pointerId:{value:1}});option.dispatchEvent(e);};
 pointer('pointerdown',10,10);assert.equal(s.submissions(),0);
 pointer('pointermove',10,35);pointer('pointerup',10,35);assert.equal(s.submissions(),0);
 pointer('pointerdown',10,10);pointer('pointercancel',10,10);pointer('pointerup',10,10);assert.equal(s.submissions(),0);
 pointer('pointerdown',10,10);pointer('pointerup',10,10);assert.equal(s.submissions(),1);
});
