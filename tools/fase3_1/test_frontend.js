// Funciones reales de portada con DOM simulado: ninguna carga de imágenes ni fetch.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../app/static/js/landing-news.js'), 'utf8');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.attributes = {}; }
  append(...children) { this.children.push(...children); }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener() {}
}
const context = vm.createContext({
  URL, window: { location: { origin: 'https://trendwatch.invalid' } },
  document: { createElement: tag => new Element(tag) },
  fetch() { throw new Error('Red prohibida'); },
});
const start = source.indexOf('  function safeUrl(');
const end = source.indexOf('  function carousel(', start);
assert.ok(start >= 0 && end > start);
vm.runInContext(source.slice(start, end), context);

const publication = { id: 7, titulo: 'Archivo', imagen_url: '/media/publicaciones/local.png',
  categorias_detalle: [{ id: 1, nombre: 'Salud' }, { id: 2, nombre: 'Turismo' }],
  fuente: 'El Territorio (Archivo)' };
assert.deepEqual(Array.from(context.categoriesOf(publication)), ['salud', 'turismo']);
const card = context.card(publication);
assert.equal(card.tag, 'a');
assert.equal(card.href, '/noticia/7/');
assert.equal(card.children[0].children.find(n => n.tag === 'img').src,
  'https://trendwatch.invalid/media/publicaciones/local.png');
assert.equal(card.children[0].children.find(n => n.className === 'photo-credit').textContent,
  '© Foto: El Territorio');

assert.deepEqual(Array.from(context.categoriesOf({categorias_detalle: [], categorias: ['Sociedad'],
  fuente: 'El Territorio (Sociedad)'})), []);

const external = context.card({ url: 'https://example.invalid/noticia', titulo: 'Externa' });
assert.equal(external.href, 'https://example.invalid/noticia');
assert.equal(external.target, '_blank');
assert.equal(external.rel, 'noopener noreferrer');

const unsafe = context.card({ url: 'javascript:alert(1)', imagen_url: 'javascript:alert(2)',
  titulo: '<script>dato</script>' });
assert.equal(unsafe.tag, 'article');
assert.equal(unsafe.children[0].children.length, 1);
assert.equal(unsafe.children[1].children.find(n => n.tag === 'h3').textContent, '<script>dato</script>');
console.log('4 escenarios de integración frontend: OK; DOM simulado, sin red.');
