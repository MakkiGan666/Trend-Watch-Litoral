# Perfil de usuario

El nombre de la navbar abre `/perfil/` para cualquier cuenta autenticada, incluidas las cuentas sin permisos de administrador. El acceso no concede permisos de gestión de publicaciones.

- **Mis datos:** nombre, apellido, email, fecha de nacimiento y celular opcionales. Cambiar el email exige la contraseña actual y rechaza emails registrados por otra cuenta. La contraseña se modifica mediante `PasswordChangeForm`, conservando la sesión actual.
- **Mis guardados:** lista privada paginada de noticias guardadas. Cada noticia permite guardar o retirar el guardado; repetir el guardado no crea duplicados. No se acepta un identificador de usuario enviado por el cliente.
- **Notificaciones:** reutiliza el permiso y la preferencia del navegador existentes. No implementa envío de avisos ni sincronización de preferencias entre dispositivos.

La migración `0010_perfilusuario_publicacionguardada` agrega `PerfilUsuario` y `PublicacionGuardada`, vinculados a `AUTH_USER_MODEL`. Los nombres, apellidos y email permanecen en la cuenta de autenticación existente. El perfil adicional se crea al guardar los datos, sin crear registros durante consultas GET.

## Puesta en marcha

```powershell
docker compose exec web python manage.py migrate
```

## Verificación

```powershell
docker compose exec web python manage.py test core.test_perfil core.test_auth_views core.test_comentarios core.test_valoraciones --noinput
```

Resultado de implementación: 32 pruebas aprobadas. Incluye acceso sin privilegios, aislamiento entre cuentas, protección CSRF, validación de datos, confirmación para cambio de email, cambio de contraseña y guardados idempotentes.
