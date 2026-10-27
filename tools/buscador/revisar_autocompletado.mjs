/* Firefox BiDi + WebSocket nativo de Node 20; sin paquetes instalados. */
import fs from 'node:fs';
const [port,base,out,nojs] = process.argv.slice(2);
if (!port || !base?.startsWith('http://127.0.0.1:') || !out) throw Error('Uso: puerto URL-local carpeta [sin-js]');
fs.mkdirSync(out,{recursive:true});
const ws=new WebSocket(`ws://127.0.0.1:${port}/session`);
await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
let networkMode='normal', requests=0;
let id=0,blocked=0;const pending=new Map(),checks=[],screens=[];
const call=(method,params={})=>new Promise((resolve,reject)=>{
  const n=++id;pending.set(n,{resolve,reject});ws.send(JSON.stringify({id:n,method,params}));
  setTimeout(()=>{if(pending.has(n)){pending.delete(n);reject(Error('Timeout '+method));}},25000).unref();
});
ws.onmessage=e=>{
  const m=JSON.parse(e.data);
  if(m.id){const p=pending.get(m.id);if(p){pending.delete(m.id);m.type==='error'?p.reject(Error(JSON.stringify(m))):p.resolve(m.result);}}
  else if(m.method==='network.beforeRequestSent' && m.params.isBlocked){
    const suggestion=m.params.request.url.includes('/api/publicaciones/sugerencias/');
    if(suggestion) requests++;
    const allow=m.params.request.url.startsWith(base+'/') && !(suggestion && networkMode==='fail');
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
const fill=async value=>evaluate(`(()=>{const i=document.getElementById('page-search-q');i.value=${JSON.stringify(value)};i.focus();i.dispatchEvent(new Event('input',{bubbles:true}));return true})()`);
const opened=`document.getElementById('page-search-q').getAttribute('aria-expanded')==='true'`;
const point=async(selector,type='mouse',drag=false)=>{
 const p=await evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});e.scrollIntoView({block:'center'});const r=e.getBoundingClientRect();return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)}})()`);
 const actions=[{type:'pointerMove',x:p.x,y:p.y},{type:'pointerDown',button:0}];
 if(drag) actions.push({type:'pointerMove',x:p.x,y:p.y+35,duration:250});
 actions.push({type:'pointerUp',button:0});
 await call('input.performActions',{context,actions:[{type:'pointer',id:'puntero-'+type,parameters:{pointerType:type},actions}]});
};
const fresh=async()=>{await navigate('/buscar/');await wait(`document.getElementById('page-search-q').getAttribute('role')==='combobox'`);};
try{
 if(nojs==='sin-js'){
  await viewport(390,844);await navigate('/buscar/');
  await check('Sin JS: enlace y ausencia de panel',`!document.querySelector('[data-search-fallback]').hidden && !document.querySelector('[role=listbox]')`);
  await fill('educacion');await point('#page-search-q + button');
  await wait(`location.search.includes('educacion') && document.querySelectorAll('.search-result').length===20`);
  await check('Sin JS: GET y paginación',`document.querySelector('.search-pagination a').href.includes('q=educacion')`);
  await shot('sin-js-390');
 }else{
  await viewport(1440,1000);await fresh();
  await fill('');
  await evaluate(`(()=>{window.teclas=[];document.addEventListener('keydown',e=>teclas.push({key:e.key,trusted:e.isTrusted}));return true})()`);
  await key('e');await key('d');await wait(opened);
  await check('Entrada nativa produce sugerencias',`document.getElementById('page-search-q').value==='ed' && teclas.every(e=>e.trusted)`);
  await check('Dos grupos y opciones limitadas',`document.querySelectorAll('#page-search-q-suggestions [role=group]').length===2 && document.querySelectorAll('#page-search-q-suggestions [role=option]').length<=9`);
  await key(String.fromCodePoint(0xE015));
  await check('Flecha y activedescendant',`document.getElementById('page-search-q').getAttribute('aria-activedescendant').endsWith('-0') && document.activeElement.id==='page-search-q'`);
  await shot('sugerencias-1440');
  await key(String.fromCodePoint(0xE00C));
  await check('Escape conserva foco y texto',`!(${opened}) && document.activeElement.id==='page-search-q' && document.activeElement.value==='ed'`);
  await fill('ed');await wait(opened);await key(String.fromCodePoint(0xE015));await key(String.fromCodePoint(0xE006));
  await wait(`location.search.includes('Educaci') && document.querySelectorAll('.search-result').length===20`);
  await check('Enter nativo selecciona término y busca',`document.getElementById('page-search-q').value==='Educación'`);
  await fresh();await fill('educacion');await wait(opened);
  await key(String.fromCodePoint(0xE006));
  await wait(`location.search.includes('q=educacion') && document.querySelectorAll('.search-result').length===20`);
  await check('Enter sin opción conserva GET nativo',`document.getElementById('page-search-q').value==='educacion'`);
  await fresh();await fill('ed');await wait(opened);
  await point('#page-search-q-suggestions [role=group]:last-child [role=option]');
  await wait(`location.pathname.startsWith('/noticia/')`);
  await check('Clic nativo navega al detalle',`document.querySelector('main')!==null`);
  await viewport(390,844);await fresh();await fill('ed');await wait(opened);
  await check('Móvil sin desbordes',noOverflow);await shot('sugerencias-390');
  await point('#page-search-q-suggestions [role=option]','touch',true);
  await check('Arrastre táctil no navega',`location.pathname==='/buscar/' && !location.search`);
  await fill('ed');await wait(opened);await point('#page-search-q-suggestions [role=option]','touch');
  await wait(`location.search.includes('Educaci')`);
  await check('Toque selecciona término',`document.querySelectorAll('.search-result').length===20`);
  await fresh();networkMode='fail';await fill('ed');await wait(`!(${opened})`);
  await new Promise(resolve=>setTimeout(resolve,700));
  await check('Fallo de red cierra sugerencias y conserva formulario',`!(${opened}) && document.getElementById('page-search-q').value==='ed' && !document.querySelector('#page-search-q + button').disabled`);
  await point('#page-search-q + button');await wait(`location.search.includes('q=ed') && document.querySelectorAll('.search-result').length===20`);
  await check('Búsqueda tradicional funciona con sugerencias caídas',`document.querySelector('.search-summary').textContent.includes('43')`);
  networkMode='normal';await fresh();await fill('inexistentezz');
  await new Promise(resolve=>setTimeout(resolve,700));
  await check('Vacío sin panel',`!(${opened})`);
  await fill('ed');await wait(opened);await point('[data-search-toggle]');
  await evaluate(`(()=>{const i=document.getElementById('nav-search-q');i.value='ed';i.dispatchEvent(new Event('input',{bubbles:true}));return true})()`);
  await wait(`document.getElementById('nav-search-q').getAttribute('aria-expanded')==='true'`);
  await key(String.fromCodePoint(0xE00C));
  await check('Primer Escape cierra sólo sugerencias de barra',`!document.getElementById('public-search-row').hidden && document.getElementById('nav-search-q').getAttribute('aria-expanded')==='false'`);
  await key(String.fromCodePoint(0xE00C));
  await check('Segundo Escape pliega barra y restaura foco',`document.getElementById('public-search-row').hidden && document.activeElement.matches('[data-search-toggle]')`);
 }
 fs.writeFileSync(`${out}/revision${nojs?'-sin-js':''}.json`,JSON.stringify({browser:session.capabilities.browserVersion,checks,screens,requests,blockedExternal:blocked},null,2));
 console.log(JSON.stringify({comprobaciones:checks.length,todas:true,capturas:screens}));
}catch(error){
 fs.writeFileSync(`${out}/fallo${nojs?'-sin-js':''}.json`,JSON.stringify({error:String(error),checks,estado:await evaluate(`({url:location.href,active:document.activeElement.id,panel:document.querySelector('[role=listbox]')?.outerHTML.slice(0,500)})`)},null,2));
 console.error(String(error));process.exitCode=1;
}finally{await call('session.end').catch(()=>{});ws.close();}
