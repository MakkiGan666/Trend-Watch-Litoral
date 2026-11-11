// Comprueba cada motor de IA: conexión al servicio y capacidad de generación (POST al panel;
// ninguna prueba ejecuta un análisis ni guarda datos).
(function () {
  'use strict';
  var token = document.querySelector('[name=csrfmiddlewaretoken]');
  var tarjetas = document.querySelectorAll('.motor-ia__estado[data-url]');
  if (!token || !tarjetas.length || !window.fetch) { return; }

  function mostrar(bloque, estado, etiqueta, detalle) {
    var pill = bloque.querySelector('[data-pill]');
    pill.setAttribute('data-estado', estado);
    pill.textContent = etiqueta;
    bloque.querySelector('[data-detalle]').textContent = detalle;
  }

  function probar(tarjeta, alcance) {
    var bloque = tarjeta.querySelector('[data-alcance="' + alcance + '"]');
    var boton = bloque.querySelector('[data-probar]');
    var cuerpo = new URLSearchParams();
    cuerpo.append('alcance', alcance);
    boton.disabled = true;
    mostrar(bloque, 'comprobando', 'Comprobando…', 'Consultando el servicio…');
    return fetch(tarjeta.getAttribute('data-url'), {
      method: 'POST',
      headers: { 'X-CSRFToken': token.value, 'X-Requested-With': 'XMLHttpRequest' },
      body: cuerpo,
      credentials: 'same-origin'
    }).then(function (respuesta) {
      if (!respuesta.ok) { throw new Error('http'); }
      return respuesta.json();
    }).then(function (datos) {
      mostrar(bloque, datos.estado, datos.etiqueta, datos.detalle);
    }).catch(function () {
      mostrar(bloque, 'error_conexion', 'Error de conexión', 'No se pudo completar la comprobación.');
    }).then(function () {
      boton.disabled = false;
    });
  }

  Array.prototype.forEach.call(tarjetas, function (tarjeta) {
    Array.prototype.forEach.call(tarjeta.querySelectorAll('[data-probar]'), function (boton) {
      boton.addEventListener('click', function () { probar(tarjeta, boton.getAttribute('data-probar')); });
    });
  });
  // Comprobación inicial: sólo de conexión (no consume llamadas de generación), de a un motor por vez.
  Array.prototype.reduce.call(tarjetas, function (previa, tarjeta) {
    return previa.then(function () { return probar(tarjeta, 'conexion'); });
  }, Promise.resolve());
})();
