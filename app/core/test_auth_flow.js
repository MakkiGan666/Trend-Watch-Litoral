// Ejecutar desde la raíz: node app/core/test_auth_flow.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { runInNewContext } = require('node:vm');

const source = readFileSync(resolve(__dirname, '../static/js/auth-flow.js'), 'utf8');

function fixture(hasError) {
  class Element extends EventTarget {
    constructor() {
      super();
      this.hidden = false;
      this.value = '';
      this.dataset = {};
    }
    setAttribute() {}
    setCustomValidity() {}
    focus() {}
    reportValidity() { return true; }
  }
  const nodes = new Map();
  const get = selector => {
    if (!nodes.has(selector)) nodes.set(selector, new Element());
    return nodes.get(selector);
  };
  const modal = new Element();
  const form = new Element();
  const error = hasError ? new Element() : null;
  if (hasError) form.dataset.authError = 'true';
  form.querySelector = selector => selector === '[data-auth-error-message]' ? error : get(selector);
  form.closest = () => modal;
  get('[data-auth-registration]').querySelector = get;
  get('[name="password"]').value = 'contraseña presente al cargar';
  const document = { querySelectorAll: () => [form], querySelector: () => null };
  runInNewContext(source, { document });
  return { form, modal, error, get };
}

test('el error permanece al cargar y se oculta al cerrar y reiniciar', () => {
  const { form, modal, error, get } = fixture(true);
  assert.equal(error.hidden, false);
  assert.equal(get('[name="password"]').value, 'contraseña presente al cargar');
  assert.equal(get('[data-auth-password-step]').hidden, false);
  modal.dispatchEvent(new Event('auth:reset'));
  assert.equal(error.hidden, true);
  assert.equal(form.dataset.authError, undefined);
  assert.equal(get('[name="password"]').value, '');
  assert.equal(get('[data-auth-password-step]').hidden, true);
  // Reabrir no recarga el DOM; avanzar otra vez tampoco revive el error anterior.
  form.dispatchEvent(new Event('submit', { cancelable: true }));
  assert.equal(get('[data-auth-password-step]').hidden, false);
  assert.equal(error.hidden, true);
  // Un POST fallido nuevo entrega un formulario nuevo con su error visible.
  assert.equal(fixture(true).error.hidden, false);
});

test('volver al identificador reinicia el error y el formulario sin error funciona', () => {
  const failed = fixture(true);
  failed.get('[data-auth-back]').dispatchEvent(new Event('click'));
  assert.equal(failed.error.hidden, true);
  assert.equal(failed.get('[name="password"]').value, '');
  const clean = fixture(false);
  clean.modal.dispatchEvent(new Event('auth:reset'));
  clean.form.dispatchEvent(new Event('submit', { cancelable: true }));
  assert.equal(clean.get('[data-auth-password-step]').hidden, false);
});
