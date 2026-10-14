(function () {
  'use strict';

  document.querySelectorAll('[data-auth-flow]').forEach(form => {
    const loginUrl = form.dataset.loginUrl;
    const registerUrl = form.dataset.registerUrl;
    const fields = form.querySelector('[data-auth-fields]');
    const registration = form.querySelector('[data-auth-registration]');
    const title = form.querySelector('[data-auth-title]');
    const description = form.querySelector('[data-auth-description]');
    const loginMessage = form.querySelector('[data-login-message]');
    const registerMessage = registration.querySelector('[data-registration-message]');
    const registerButton = form.querySelector('[data-auth-register]');
    const loginButton = form.querySelector('[data-auth-login]');
    const modal = form.closest('.login-modal');
    let mode = 'login';

    function setMode(value, focus = true) {
      mode = value;
      const registering = mode === 'register';
      fields.hidden = registering;
      fields.querySelectorAll('input').forEach(input => {
        input.disabled = registering;
      });
      registration.hidden = !registering;
      registration.disabled = !registering;
      form.action = registering ? registerUrl : loginUrl;
      title.textContent = registering ? 'Registrate en TrendWatch' : 'Iniciá sesión o registrate';
      description.textContent = registering
        ? 'Una cuenta para seguir la conversación del Litoral.'
        : 'Continuá con tu email o nombre de usuario para acceder a TrendWatch.';
      registerMessage.hidden = true;
      loginMessage.hidden = true;
      if (focus) {
        const selector = registering ? '[name="username"]' : '#id_modal_username';
        (registering ? registration : fields).querySelector(selector).focus();
      }
    }

    registerButton.addEventListener('click', () => setMode('register'));
    loginButton.addEventListener('click', () => setMode('login'));

    form.addEventListener('submit', async event => {
      event.preventDefault();
      const registering = mode === 'register';
      const submitButton = form.querySelector(registering ? '[data-auth-submit]' : '[data-auth-next]');
      const message = registering ? registerMessage : loginMessage;
      submitButton.disabled = true;
      message.hidden = true;

      try {
        const response = await fetch(form.action, {
          method: 'POST',
          body: new FormData(form),
          credentials: 'same-origin',
          headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        const result = await response.json();
        if (!response.ok || !result.success) {
          message.textContent = result.message || 'No se pudo completar la solicitud.';
          message.hidden = false;
          return;
        }
        window.location.assign('/');
      } catch (error) {
        message.textContent = 'No se pudo conectar con el servidor. Intentá nuevamente.';
        message.hidden = false;
      } finally {
        submitButton.disabled = false;
      }
    });

    if (modal) {
      modal.addEventListener('auth:reset', () => setMode('login', false));
    }
    setMode('login', false);
  });

  const bell = document.querySelector('[data-account-notifications]');
  if (bell) {
    const panel = document.getElementById(bell.getAttribute('aria-controls'));
    const close = () => {
      panel.hidden = true;
      bell.setAttribute('aria-expanded', 'false');
    };
    bell.addEventListener('click', () => {
      panel.hidden = !panel.hidden;
      bell.setAttribute('aria-expanded', String(!panel.hidden));
    });
    document.addEventListener('click', event => {
      if (!bell.parentElement.contains(event.target)) close();
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !panel.hidden) {
        close();
        bell.focus();
      }
    });
  }
})();
