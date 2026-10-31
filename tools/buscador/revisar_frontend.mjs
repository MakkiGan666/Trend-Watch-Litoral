/* Firefox BiDi + WebSocket nativo de Node 20; sin paquetes instalados. */
import fs from 'node:fs';
const [port,base,out,nojs] = process.argv.slice(2);
if (!port || !base?.startsWith('http://127.0.0.1:') || !out) throw Error('Uso: puerto URL-local carpeta [sin-js]');
fs.mkdirSync(out,{recursive:true});
const ws=new WebSocket(`ws://127.0.0.1:${port}/session`);
await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
let id=0,blocked=0;const pending=new Map(),checks=[],screens=[];
const call=(method,params={})=>new Promise((resolve,reject)=>{
  const n=++id;pending.set(n,{resolve,reject});ws.send(JSON.stringify({id:n,method,params}));
  setTimeout(()=>{if(pending.has(n)){pending.delete(n);reject(Error('Timeout '+method));}},25000).unref();
});
ws.onmessage=e=>{
  const m=JSON.parse(e.data);
  if(m.id){const p=pending.get(m.id);if(p){pending.delete(m.id);m.type==='error'?p.reject(Error(JSON.stringify(m))):p.resolve(m.result);}}
  else if(m.method==='network.beforeRequestSent' && m.params.isBlocked){
    const allow=m.params.request.url.startsWith(base+'/');
    if(!allow) blocked++;
    call(allow?'network.continueRequest':'network.failRequest',{request:m.params.request.request}).catch(()=>{});
  }
};
const session=await call('session.new',{capabilities:{alwaysMatch:{}}});
const tree=await call('browsingContext.getTree');const context=tree.contexts[0].context;
await call('session.subscribe',{events:['network.beforeRequestSent']});
await call('network.addIntercept',{phases:['beforeRequestSent']});
const evaluate=async expression=>{
  const r=await call('script.evaluate',{expression:`JSON.stringify(${expression})`,target:{context},awaitPromise:true});
  if(r.type==='exception') throw Error(JSON.stringify(r.exceptionDetails));
  return JSON.parse(r.result.value);
};
const wait=async expression=>{
  for(let n=0;n<60;n++){
    try{if(await evaluate(expression)) return;}catch(e){}
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  throw Error('No se cumplió: '+expression);
};
const check=async (label,expression)=>{
  const ok=await evaluate(expression);checks.push({label,ok:!!ok});if(!ok)throw Error(label);
};
const navigate=async path=>{await call('browsingContext.navigate',{context,url:base+path,wait:'complete'});};
const viewport=async(width,height)=>call('browsingContext.setViewport',{context,viewport:{width,height},devicePixelRatio:1});
const key=async value=>call('input.performActions',{context,actions:[{type:'key',id:'teclado',actions:[{type:'keyDown',value},{type:'keyUp',value}]}]});
const shot=async nombre=>{
  await new Promise(resolve=>setTimeout(resolve,300));
  const r=await call('browsingContext.captureScreenshot',{context,origin:'viewport'});
  fs.writeFileSync(`${out}/${nombre}.png`,Buffer.from(r.data,'base64'));screens.push(nombre+'.png');
};
const noOverflow=`document.documentElement.scrollWidth <= window.innerWidth && [...document.querySelectorAll('.nav .public-search-toggle,.nav__act,.public-nav-toggle,.public-search-row:not([hidden]) input')].filter(e=>e.getClientRects().length).every(e=>e.getBoundingClientRect().left>=0 && e.getBoundingClientRect().right<=innerWidth+1)`;
try{
  if(nojs==='sin-js'){
    await viewport(390,844);await navigate('/buscar/');
    await check('Sin JS: enlace alternativo visible',`!document.querySelector('[data-search-fallback]').hidden && document.querySelector('[data-search-toggle]').hidden`);
    await evaluate(`(()=>{const i=document.querySelector('#page-search-q');i.value='educacion';i.focus();return true})()`);
    await evaluate(`(()=>{document.activeElement.form.querySelector('button[type=submit]').click();return true})()`);await wait(`document.querySelectorAll('.search-result').length===20`);
    await check('Sin JS: formulario GET produce resultados',`location.search.includes('educacion') && document.querySelectorAll('mark').length>0`);
    await check('Sin JS: paginación enlazada',`document.querySelector('.search-pagination a').href.includes('page=2')`);
    await shot('sin-javascript-movil');
  }else{
    await viewport(1440,1000);await navigate('/buscar/?q=educacion');
    await wait(`!document.querySelector('[data-search-toggle]').hidden`);
    await check('20 resultados renderizados',`document.querySelectorAll('.search-result').length===20`);
    await check('Escritorio sin desbordes',noOverflow);
    await shot('resultados-escritorio');
    await evaluate(`(()=>{document.querySelector('[data-search-toggle]').focus();return true})()`);
    await evaluate(`(()=>{document.querySelector('[data-search-toggle]').click();return true})()`);await wait(`!document.getElementById('public-search-row').hidden`);
    await check('Abrir enfoca campo',`document.activeElement.id==='nav-search-q' && document.querySelector('[data-search-toggle]').getAttribute('aria-expanded')==='true'`);
    await evaluate(`(()=>{document.getElementById('nav-search-q').value='texto conservado';return true})()`);
    await key(String.fromCodePoint(0xE00C));
    await check('Escape cierra y devuelve foco',`document.getElementById('public-search-row').hidden && document.activeElement.matches('[data-search-toggle]')`);
    await evaluate(`(()=>{document.querySelector('[data-search-toggle]').click();return true})()`);
    await check('Conserva texto al plegar',`document.getElementById('nav-search-q').value==='texto conservado'`);
    await evaluate(`(()=>{document.querySelector('[data-search-toggle]').click();return true})()`);
    await check('Segunda pulsación cierra',`document.getElementById('public-search-row').hidden && document.activeElement.matches('[data-search-toggle]')`);
    await viewport(390,844);await navigate('/buscar/?q=educacion');
    await check('Móvil anónimo sin desbordes',noOverflow);await shot('resultados-movil');
    await navigate('/');await wait(`!document.querySelector('[data-search-toggle]').hidden`);
    await evaluate(`(()=>{document.querySelector('#public-nav-toggle').click();document.querySelector('[data-search-toggle]').click();return true})()`);
    await check('Buscar cierra menú móvil',`!document.getElementById('public-search-row').hidden && document.querySelector('#public-nav-toggle').getAttribute('aria-expanded')==='false'`);
    await evaluate(`(()=>{document.getElementById('nav-search-q').value='educacion';return true})()`);
    await check('Barra Inicio móvil completa',noOverflow);await shot('inicio-movil-barra');
    await evaluate(`(()=>{document.activeElement.form.querySelector('button[type=submit]').click();return true})()`);await wait(`location.pathname==='/buscar/' && document.querySelectorAll('.search-result').length===20 && !document.querySelector('[data-search-toggle]').hidden`);
    await evaluate(`(()=>{document.querySelector('[data-search-toggle]').click();document.querySelector('.nav__act [aria-haspopup="dialog"]').click();return true})()`);
    await wait(`document.getElementById('login-modal').classList.contains('is-open')`);
    await check('Cuenta sin conflicto con barra',`document.getElementById('public-search-row').hidden && !document.getElementById('login-modal').hidden`);
    await evaluate(`(()=>{document.getElementById('id_modal_username').focus();return true})()`);
    await key(String.fromCodePoint(0xE00C));
    await check('Escape de cuenta conserva su comportamiento',`document.getElementById('login-modal').hidden`);
    await navigate('/preview/sesion/');await viewport(320,800);
    await wait(`document.querySelector('.nav__act a[href="/perfil/"]')!==null`);
    await evaluate(`(()=>{document.querySelector('[data-search-toggle]').click();return true})()`);
    await check('Móvil autenticado 320px sin desbordes',noOverflow);await shot('cuenta-movil-320');
    await navigate('/buscar/?q=inexistentezz');await check('Estado vacío',`document.querySelector('.search-empty')!==null && document.querySelectorAll('.search-result').length===0`);
    await navigate('/buscar/?q=x');await check('Error conserva consulta',`document.getElementById('search-error')!==null && document.getElementById('page-search-q').value==='x'`);
    await navigate('/buscar/?q=educacion&page=2');
    await check('Paginación conserva consulta',`document.getElementById('page-search-q').value==='educacion' && document.querySelector('.search-pagination').textContent.includes('Página 2')`);
    await evaluate(`(()=>{document.querySelectorAll('[data-search-image]').forEach(i=>i.loading='eager');return true})()`);
    await wait(`Array.from(document.querySelectorAll('[data-search-image]')).every(i=>i.complete)`);
    await check('Imágenes fallidas no ocultan el texto',`Array.from(document.querySelectorAll('[data-search-image]')).some(i=>i.naturalWidth===0) && Array.from(document.querySelectorAll('[data-search-image]')).filter(i=>i.naturalWidth===0).every(i=>i.closest('.search-result__image').hidden && i.closest('article').querySelector('h3 a').getClientRects().length>0)`);
    await viewport(1440,1000);await navigate('/categorias/');await check('Categorías comparte la lupa',`document.querySelectorAll('[data-search-toggle]').length===1`);
  }
  fs.writeFileSync(`${out}/revision${nojs?'-sin-js':''}.json`,JSON.stringify({browser:session.capabilities.browserVersion,checks,screens,blockedExternal:blocked},null,2));
  console.log(JSON.stringify({comprobaciones:checks.length,todas:true,capturas:screens}));
}catch(error){
  fs.writeFileSync(`${out}/fallo.json`,JSON.stringify({error:String(error),checks,estado:await evaluate(`({active:document.activeElement.outerHTML.slice(0,220),row:document.getElementById('public-search-row')?.hidden,modal:document.getElementById('login-modal')?.hidden})`)},null,2));
  console.error(String(error));process.exitCode=1;
}finally{await call('session.end').catch(()=>{});ws.close();}
