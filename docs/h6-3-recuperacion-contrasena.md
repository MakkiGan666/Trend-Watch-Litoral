# H6.3 — Recuperación segura de contraseña

El flujo usa `PasswordResetView`, `PasswordResetConfirmView` y los componentes
nativos de Django. Los enlaces incluyen UID y token firmado por Django, vencen
según `PASSWORD_RESET_TIMEOUT` (tres días por defecto) y dejan de ser válidos
al cambiar la contraseña. Las vistas usan POST con CSRF y redirecciones locales
fijas.

La confirmación de solicitud no distingue entre direcciones existentes,
desconocidas, cuentas sin email o direcciones ambiguas. Solo se envía un enlace
cuando el email identifica exactamente una cuenta activa con contraseña
utilizable. No se modifican cuentas históricas sin email ni se intenta resolver
emails duplicados; esas personas deben recuperar acceso por un canal de soporte
que el equipo defina.

El backend por defecto es `django.core.mail.backends.locmem.EmailBackend` y no
entrega mensajes fuera del proceso. En pruebas se inspecciona `mail.outbox`.
Para habilitar usuarios reales, una etapa operativa deberá configurar por entorno
un backend de correo seguro, remitente, TLS, credenciales fuera del repositorio,
dominio permitido y monitoreo que nunca registre cuerpos, tokens ni contraseñas.
Hasta entonces, el enlace no llega a la persona usuaria y la función no debe
presentarse como recuperación operativa.

No se agregó migración ni se alteró el login por username/email. Antes de usar el
flujo con cuentas existentes, el equipo debe revisar por canal administrativo
controlado la cobertura y unicidad de emails, sin exponer esos datos en logs.
