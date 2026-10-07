(function () {
  'use strict';
  const dialog = document.querySelector('#notification-prompt');
  if (!dialog || typeof dialog.show !== 'function') return;
  const key = 'trendwatch.notifications.v1';
  const yes = dialog.querySelector('[data-notification-yes]');
  const no = dialog.querySelector('[data-notification-no]');
  const choices = dialog.querySelector('[data-notification-choices]');
  const done = dialog.querySelector('[data-notification-done]');
  const result = dialog.querySelector('[data-notification-result]');
  let memory = null;
  let pending = false;
  function read() {
    for (const store of ['localStorage', 'sessionStorage']) {
      try {
        const value = JSON.parse(window[store].getItem(key));
        if (value && ['accepted', 'declined', 'dismissed'].includes(value.choice)) return value;
      } catch (_) { /* La elección también se mantiene en memoria. */ }
    }
    return memory;
  }
  function remember(choice) {
    memory = { choice, updatedAt: new Date().toISOString() };
    for (const store of ['localStorage', 'sessionStorage']) {
      try { window[store].setItem(key, JSON.stringify(memory)); } catch (_) {}
    }
  }
  function supported() { return 'Notification' in window && window.isSecureContext && typeof window.Notification.requestPermission === 'function'; }
  function permission() { return supported() ? window.Notification.permission : 'unsupported'; }
  function sync() {
    const choice = read();
    let message = 'Todavía no elegiste si querés recibir avisos.';
    if (choice && choice.choice === 'declined') message = 'Elegiste no recibir notificaciones.';
    else if (permission() === 'granted') message = 'El permiso del navegador está habilitado.';
    else if (permission() === 'denied') message = 'El navegador bloquea las notificaciones. Podés cambiarlo en los permisos del sitio.';
    else if (choice && choice.choice === 'accepted') message = 'Tu elección está guardada; el permiso del navegador todavía no fue concedido.';
    else if (permission() === 'unsupported') message = 'Este navegador o conexión no admite permisos de notificaciones.';
    document.querySelectorAll('[data-notification-status]').forEach(el => { el.textContent = message; });
  }
  function finish(message) {
    result.textContent = message;
    choices.hidden = true;
    done.hidden = false;
    done.focus();
    sync();
  }
  function open() {
    if (dialog.open || document.body.classList.contains('login-modal-open')) return;
    result.textContent = '';
    choices.hidden = false;
    done.hidden = true;
    yes.disabled = no.disabled = false;
    dialog.show();
    if (permission() === 'denied') finish('Las notificaciones están bloqueadas por el navegador. Para habilitarlas, cambiá los permisos de este sitio.');
  }
  function close() {
    if (pending) return;
    if (!read()) remember('dismissed');
    dialog.close();
    sync();
  }
  yes.addEventListener('click', async () => {
    if (pending) return;
    remember('accepted');
    if (!supported()) {
      finish('Guardamos tu elección. Este navegador o conexión no permite habilitar notificaciones.');
      return;
    }
    if (permission() === 'granted') {
      finish('El permiso ya está habilitado. El envío de avisos estará disponible próximamente.');
      return;
    }
    pending = true;
    yes.disabled = no.disabled = true;
    result.textContent = 'Elegí una opción en el aviso de tu navegador.';
    try {
      // Se solicita exclusivamente dentro del clic del usuario.
      const value = await window.Notification.requestPermission();
      finish(value === 'granted'
        ? 'Permiso habilitado. El envío de avisos estará disponible próximamente.'
        : (value === 'denied' ? 'El navegador bloqueó el permiso. No se enviarán notificaciones.' : 'Guardamos tu elección. El permiso del navegador quedó pendiente.'));
    } catch (_) {
      finish('Guardamos tu elección, pero no se pudo solicitar el permiso. Podés volver a intentarlo desde la campana.');
    } finally { pending = false; }
  });
  no.addEventListener('click', () => { remember('declined'); dialog.close(); sync(); });
  done.addEventListener('click', close);
  dialog.querySelector('[data-notification-close]').addEventListener('click', close);
  dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
  document.querySelectorAll('[data-notification-configure]').forEach(button => {
    button.addEventListener('click', () => {
      const panel = document.querySelector('#account-notifications-panel');
      const bell = document.querySelector('[data-account-notifications]');
      if (panel) panel.hidden = true;
      if (bell) bell.setAttribute('aria-expanded', 'false');
      open();
    });
  });
  window.addEventListener('storage', event => { if (event.key === key) { sync(); if (read() && dialog.open && !pending) dialog.close(); } });
  window.addEventListener('focus', sync);
  sync();
  if (dialog.dataset.notificationAuto === 'true' && !read() && permission() === 'default') {
    setTimeout(() => {
      if (read()) return;
      if (!document.body.classList.contains('login-modal-open')) open();
      else {
        const observer = new MutationObserver(() => {
          if (!document.body.classList.contains('login-modal-open')) { observer.disconnect(); if (!read()) open(); }
        });
        observer.observe(document.body, { attributes: true, attributeFilter: ['class'] });
      }
    }, 1500);
  }
})();
