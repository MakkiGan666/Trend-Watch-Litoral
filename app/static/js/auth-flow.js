(function () {
  'use strict';
  document.querySelectorAll('[data-auth-flow]').forEach(form => {
    const email = form.querySelector('[name="username"]');
    const password = form.querySelector('[name="password"]');
    const passwordStep = form.querySelector('[data-auth-password-step]');
    const providers = form.querySelector('[data-auth-providers]');
    const next = form.querySelector('[data-auth-next]');
    const back = form.querySelector('[data-auth-back]');
    const title = form.querySelector('[data-auth-title]');
    const description = form.querySelector('[data-auth-description]');
    const fields = form.querySelector('[data-auth-fields]');
    const registration = form.querySelector('[data-auth-registration]');
    const toggle = form.querySelector('[data-auth-password-toggle]');
    const registerPassword = registration.querySelector('[name="registration_password"]');
    const registerConfirm = registration.querySelector('[name="password_confirmation"]');
    const registerMessage = registration.querySelector('[data-registration-message]');
    const validateConfirmation = () => registerConfirm.setCustomValidity(registerConfirm.value !== registerPassword.value ? 'Las contraseñas deben coincidir.' : '');
    registerPassword.addEventListener('input', validateConfirmation);
    registerConfirm.addEventListener('input', validateConfirmation);
    let step = 'email';
    function setStep(value, focus = true) {
      step = value;
      const signingIn = value === 'password';
      fields.hidden = value === 'register';
      registration.hidden = value !== 'register';
      registration.disabled = value !== 'register';
      registerMessage.hidden = true;
      providers.hidden = signingIn;
      passwordStep.hidden = !signingIn;
      password.disabled = !signingIn;
      email.disabled = value === 'register';
      back.hidden = !signingIn;
      next.textContent = signingIn ? 'Iniciar sesión' : 'Siguiente';
      title.textContent = value === 'register' ? 'Registrate en TrendWatch' : (signingIn ? 'Ingresá tu contraseña' : 'Iniciá sesión o registrate');
      description.textContent = value === 'register' ? 'Una cuenta para seguir la conversación del Litoral.' : (signingIn ? 'Accedé con tu cuenta de TrendWatch.' : 'Continuá con tu email para acceder a TrendWatch.');
      if (!signingIn) {
        password.value = '';
        password.type = 'password';
        toggle.textContent = 'Mostrar';
        toggle.setAttribute('aria-label', 'Mostrar contraseña');
        toggle.setAttribute('aria-pressed', 'false');
      }
      if (focus) (value === 'register' ? registration.querySelector('[name="nombre"]') : (signingIn ? password : email)).focus();
    }
    form.addEventListener('submit', event => {
      if (step !== 'password') {
        event.preventDefault();
        if (step === 'email' && email.reportValidity()) setStep('password');
        if (step === 'register') {
          validateConfirmation();
          if (form.reportValidity()) {
            registerMessage.textContent = 'Los datos son válidos. La creación de cuentas estará disponible cuando se conecte el registro.';
            registerMessage.hidden = false;
          }
        }
      }
    });
    // Evita enviar una contraseña para otro email editado en el segundo paso.
    email.addEventListener('input', () => { if (step === 'password') setStep('email', false); });
    back.addEventListener('click', () => setStep('email'));
    form.querySelector('[data-auth-register]').addEventListener('click', () => setStep('register'));
    form.querySelector('[data-auth-return]').addEventListener('click', () => setStep('email'));
    toggle.addEventListener('click', () => {
      const show = password.type === 'password';
      password.type = show ? 'text' : 'password';
      toggle.textContent = show ? 'Ocultar' : 'Mostrar';
      toggle.setAttribute('aria-label', show ? 'Ocultar contraseña' : 'Mostrar contraseña');
      toggle.setAttribute('aria-pressed', String(show));
      password.focus();
    });
    const modal = form.closest('.login-modal');
    if (modal) modal.addEventListener('auth:reset', () => {
      registerPassword.value = '';
      registerConfirm.value = '';
      registerConfirm.setCustomValidity('');
      setStep('email', false);
    });
    setStep(form.dataset.authError ? 'password' : 'email', false);
  });
  const bell = document.querySelector('[data-account-notifications]');
  if (bell) {
    const panel = document.getElementById(bell.getAttribute('aria-controls'));
    const close = () => { panel.hidden = true; bell.setAttribute('aria-expanded', 'false'); };
    bell.addEventListener('click', () => { panel.hidden = !panel.hidden; bell.setAttribute('aria-expanded', String(!panel.hidden)); });
    document.addEventListener('click', event => { if (!bell.parentElement.contains(event.target)) close(); });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !panel.hidden) { close(); bell.focus(); }
    });
  }
})();
