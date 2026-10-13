// Ejecutar desde la raíz: node --test app/core/test_auth_flow.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { runInNewContext } = require('node:vm');

const source = readFileSync(resolve(__dirname, '../static/js/auth-flow.js'), 'utf8');

class Element extends EventTarget {
  constructor() {
    super();
    this.hidden = false;
    this.disabled = false;
    this.value = '';
    this.textContent = '';
    this.dataset = {};
    this.attributes = {};
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  focus() {}
  querySelector() { return this.child; }
  querySelectorAll() { return this.inputs || []; }
}

function fixture(fetchResponse) {
  const nodes = new Map();
  const get = selector => {
    if (!nodes.has(selector)) nodes.set(selector, new Element());
    return nodes.get(selector);
  };
  const form = get('form');
  form.dataset = { loginUrl: '/login/', registerUrl: '/registro/' };
  form.action = '/login/';
  form.querySelector = get;
  const fields = get('[data-auth-fields]');
  fields.querySelectorAll = () => [get('#id_modal_username'), get('#id_modal_password')];
  const registration = get('[data-auth-registration]');
  registration.querySelector = get;
  form.closest = () => get('.login-modal');
  const requests = [];
  const window = { location: { assign: url => requests.push({ redirect: url }) } };
  class FormData {
    constructor(target) { this.form = target; }
  }
  const fetch = async (url, options) => {
    requests.push({ url, options });
    return fetchResponse();
  };
  runInNewContext(source, {
    document: { querySelectorAll: () => [form], querySelector: () => null },
    window,
    FormData,
    fetch,
  });
  return { form, fields, registration, requests, get };
}

test('el modal inicia en login y cambia al endpoint y campos de registro', () => {
  const { form, fields, registration, get } = fixture(async () => ({
    ok: true,
    json: async () => ({ success: true }),
  }));

  assert.equal(form.action, '/login/');
  assert.equal(fields.hidden, false);
  assert.equal(registration.disabled, true);
  get('[data-auth-register]').dispatchEvent(new Event('click'));
  assert.equal(form.action, '/registro/');
  assert.equal(fields.hidden, true);
  assert.equal(get('#id_modal_username').disabled, true);
  assert.equal(registration.disabled, false);
});

test('el login envía la solicitud AJAX y presenta errores del servidor', async () => {
  const { form, requests, get } = fixture(async () => ({
    ok: false,
    json: async () => ({ success: false, message: 'Credenciales inválidas.' }),
  }));

  form.dispatchEvent(new Event('submit', { cancelable: true }));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests[0].url, '/login/');
  assert.equal(requests[0].options.method, 'POST');
  assert.equal(requests[0].options.headers['X-Requested-With'], 'XMLHttpRequest');
  assert.equal(get('[data-login-message]').textContent, 'Credenciales inválidas.');
  assert.equal(get('[data-login-message]').hidden, false);
});

test('el registro publica el formulario y recarga al completarse', async () => {
  const { form, requests, get } = fixture(async () => ({
    ok: true,
    json: async () => ({ success: true }),
  }));

  get('[data-auth-register]').dispatchEvent(new Event('click'));
  form.dispatchEvent(new Event('submit', { cancelable: true }));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests[0].url, '/registro/');
  assert.equal(requests[0].options.method, 'POST');
  assert.equal(requests[1].redirect, '/');
});

test('cerrar el modal vuelve al modo login', () => {
  const { form, fields, registration, get } = fixture(async () => ({
    ok: true,
    json: async () => ({ success: true }),
  }));

  get('[data-auth-register]').dispatchEvent(new Event('click'));
  get('.login-modal').dispatchEvent(new Event('auth:reset'));
  assert.equal(form.action, '/login/');
  assert.equal(fields.hidden, false);
  assert.equal(registration.disabled, true);
});
