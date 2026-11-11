# 08 — Seguridad, autenticación y permisos

Revisión estática, sin pruebas de intrusión ni ejecución. No se modificó la autenticación ni los permisos.
Ningún secreto se reproduce aquí.

## 1. Autenticación

| Canal | Mecanismo | Evidencia |
|---|---|---|
| Sitio web | Sesión de Django (`django.contrib.sessions`), login por username o email | `views.login_view`, `services/autenticacion.py` |
| Registro | POST AJAX, validadores de contraseña de Django, unicidad de identidad | `views.registro_view`, `services/identidad.py` |
| API | Simple JWT: access de 60 min, refresh de 1 día, rotación y blacklist después de rotar | `settings.SIMPLE_JWT`, `serializers.py` |
| Logout JWT | Revoca solo el refresh presentado, que debe pertenecer al usuario autenticado (si no, 403) | `views.LogoutJWTView`, `LogoutJWTSerializer` |
| Admin | Django Admin estándar (`is_staff`) | `admin.py` |

**Puntos positivos:**

- Los identificadores ambiguos (un username de una cuenta coincide con el email de otra) se rechazan sin
  elegir una cuenta, y se calcula un hash simulado para igualar tiempos de respuesta.
- `serializar_identidad` usa un `pg_advisory_xact_lock` para evitar carreras en altas y cambios de
  username o email.
- Cambiar el email exige la contraseña actual; el cambio de contraseña conserva la sesión con
  `update_session_auth_hash`.
- La vista de administradores usa `sensitive_post_parameters` y `never_cache`.

**Observaciones:**

- **Sin límite de intentos** en `/login/`, `/registro/` y `/api/auth/login/`: no hay throttling de DRF,
  middleware de rate limit ni bloqueo de cuenta. Riesgo de fuerza bruta y de altas masivas.
- `logout_view` acepta **GET** (documentado en el README). Un sitio de terceros podría cerrar la sesión
  del usuario (CSRF de logout, impacto bajo).
- `registro_view` inicia sesión inmediatamente, sin verificar el email.

## 2. Roles y autorización

`app/core/roles.py`:

| Rol | Permisos |
|---|---|
| Usuario | `core.view_publicacion` |
| Administrador | Lo anterior, más `ejecutar_scraping`, `procesar_ia`, `view_revisiondepartamento`; `view`, `add`, `change` y `delete` sobre `publicacion`, `sentimiento`, `locacion`, `registrodatos`, `tematrend`, `publicaciontema`, `userauditoria`, `votopublicacion` y `comentario`; y `auth.view_user`, `auth.add_user` y `auth.view_group` |
| Superusuario | Todo. Es el único que puede editar usuarios y grupos en el Admin (`EscrituraTecnicaMixin`) |

- `PERMISOS_PANEL` (CRUD completo de `publicacion`) protege `/publicaciones/` y `/dashboard/`. Sin sesión
  redirige al login; sin permiso responde 403.
- `puede_gestionar_administradores` exige la pertenencia al grupo Administrador **y** los permisos del
  panel más `auth.add_user`. El permiso solo no alcanza.
- La API usa clases `PermisosDjango` (`permissions.py`) combinadas con `IsAuthenticated`. La autenticación
  por defecto de DRF es solo JWT, así que **una sesión web no sirve para la API**.
- `configurar_roles` es idempotente, no reasigna superusuarios y limpia permisos individuales al asignar
  un rol.
- Los grupos históricos `Lector` y `Analista` pueden seguir dando permisos en bases antiguas aunque no se
  muestren como roles (advertido en el README).
- Los modelos legacy `Role` y `User` **no** participan de la autorización.

## 3. Protección de rutas

| Tipo | Rutas | Protección |
|---|---|---|
| Lectura pública intencional | portada, categorías, noticia, localidad, búsqueda, `/api/publicaciones/`, `/api/publicaciones/<pk>/`, buscar, sugerencias, localidades, cotizaciones | Ninguna (diseño declarado: "las consultas públicas de noticias se mantienen públicas") |
| Lector | comentar, valorar, guardar, perfil | `login_required` + `require_POST` donde corresponde |
| Autoría | editar y eliminar comentario | Comparación `autor_id` o `delete_comentario` |
| Administración | panel, dashboard, procesar IA, administradores | `permission_required`, `PermissionDenied` |
| API de escritura | crear, actualizar, eliminar, ingestar, sentimiento | JWT + permisos |

Las vistas JSON públicas (`listar_publicaciones`, `obtener_detalle_publicacion`) son funciones de Django,
no de DRF, así que la configuración `DEFAULT_PERMISSION_CLASSES = IsAuthenticated` **no se les aplica**.
Es coherente con el diseño, pero conviene saberlo.

## 4. Validaciones y exposición de datos

- **Entradas:** serializers estrictos (rechazan campos desconocidos y tipos no string), búsquedas limitadas a
  2–150 caracteres y 10 términos sin caracteres de control, paginación validada, imágenes verificadas por su
  contenido real y renombradas, fechas acotadas.
- **Salida HTML:** autoescape de Django. `presentacion_busqueda` declara que nunca marca HTML como seguro.
  `enlace_seguro` e `imagen_segura` solo aceptan `http(s)` o rutas relativas.
- **Errores de IA:** saneados antes de registrarse (ver [07 §2.1](07_inteligencia_artificial_y_RAG.md)).
- **Errores de ingesta:** registran solo el link, el hash, el título truncado y un código.
- **API pública:** `/api/publicaciones/<pk>/` devuelve el contenido completo de la noticia. Las noticias
  provienen de un medio tercero: es una consideración de derechos de autor más que de seguridad.
- **Comentarios:** se ven solo publicados (y los propios). El `username` del autor se muestra
  públicamente (`partials/_comentarios.html`, línea 21), o "Usuario eliminado" si la cuenta ya no existe.

## 5. Sesiones y cookies

- **Desarrollo** (`settings.py`): valores por defecto de Django. No hay `SESSION_COOKIE_SECURE` ni HSTS.
  `DEBUG` sale del entorno (por defecto `False`).
- **Producción** (`production_config.py`): `DEBUG=False` obligatorio, `SECRET_KEY` ≥50 caracteres y no
  `django-insecure`, `ALLOWED_HOSTS` sin comodines ni `localhost`, cookies `Secure`, `HttpOnly` y
  `SameSite=Lax`, `SECURE_SSL_REDIRECT`, proxy HTTPS solo si se declara, HSTS configurable y `sslmode`
  explícito para PostgreSQL. `settings.py` no carga `.env` cuando
  `DJANGO_SETTINGS_MODULE=mi_proyecto.settings_production`.
- **Contenedor productivo:** usuario 10001, `read_only`, `tmpfs /tmp noexec`, `cap_drop: ALL`,
  `no-new-privileges` y puerto publicado solo en `127.0.0.1:8001`.

## 6. Configuración sensible y exposiciones encontradas (sin valores)

| # | Hallazgo | Ubicación | Gravedad |
|---|---|---|---|
| S1 | `.env` local con `SECRET_KEY`, `DB_PASSWORD` y `GEMINI_API_KEY`. No está rastreado (`.gitignore`, `.dockerignore`) | `Trend-Watch-Litoral/.env` | Esperado; proteger el archivo |
| S2 | El **commit inicial** `5ece768` (03/10/2026) contenía una `SECRET_KEY` `django-insecure` en `settings.py` y una contraseña de PostgreSQL literal en `docker-compose.yml`. Se reemplazaron por variables de entorno en `32ae783` | Historial Git en GitHub (`MakkiGan666/Trend-Watch-Litoral`) | Alta si esos valores siguen en uso |
| S3 | El stash `stash@{1}` tiene la descripción de su autor "wip auth + config (contiene clave, no aplicar settings/compose)". Su contenido no se inspeccionó | `git stash list` | Media (local) |
| S4 | El `docker-compose.yml` **modificado localmente** reemplazó `${DB_PASSWORD…}` por un valor literal precedido de `$` en `POSTGRES_PASSWORD`, y lo mismo en `POSTGRES_DB` y `POSTGRES_USER`. Si se commitea, una posible credencial queda en el repositorio. Además, Compose lo interpreta como una variable inexistente (cadena vacía) | `docker-compose.yml`, líneas 8–10 (sin commitear) | Alta antes de commitear |
| S5 | Respaldo con **volcado de la base de datos** (puede contener usuarios, hashes de contraseñas, perfiles y tokens) | `..\respaldos-trendwatch-2026-11-02\db-antes-actualizacion.dump` (fuera del repositorio) | Media; restringir acceso |
| S6 | `diff_gemini.txt` (UTF-16) en la raíz del repositorio, sin seguimiento. La búsqueda de patrones de clave no encontró coincidencias | raíz | Baja; eliminar o ignorar |
| S7 | `test_ingesta.py` lee credenciales de prueba de las variables `TW_TEST_USER` y `TW_TEST_PASSWORD` (correcto) y **crea publicaciones** en el servidor al que apunta | raíz | Baja; no usar contra datos reales |

## 7. Dependencias con posibles riesgos

| Dependencia | Observación |
|---|---|
| `newspaper3k==0.2.8` | Sin mantenimiento desde 2018 y procesa HTML de terceros. El riesgo se mitiga porque el HTML llega por el transporte controlado (`input_html=`) y `fetch_images=False`. Considerar `newspaper4k` o un extractor mantenido |
| `pandas`, `scipy`, `feedparser` | No se usan: aumentan la superficie y el tamaño de la imagen sin beneficio |
| `psycopg2-binary` | Adecuado para desarrollo; la documentación de psycopg recomienda compilar `psycopg2` para producción |
| Versiones fijadas | Todas fijadas con `==`. Una revisión de CVE contra estas versiones queda **NO VERIFICADA** (no se ejecutó `pip-audit`, que requiere red e instalación) |

## 8. Recomendaciones de seguridad

1. Rotar `SECRET_KEY`, la contraseña de PostgreSQL y `GEMINI_API_KEY` si coinciden con valores del commit
   inicial, del stash o de los respaldos.
2. No commitear el `docker-compose.yml` local. Restaurar la interpolación `${DB_PASSWORD:?…}`.
3. Agregar rate limiting a login, registro y JWT (por ejemplo, `DEFAULT_THROTTLE_CLASSES` de DRF y un
   middleware o paquete para las vistas HTML).
4. Hacer que `/logout/` acepte solo POST.
5. Ejecutar `pip-audit` en un entorno aislado y retirar las dependencias sin uso.
6. Registrar en `Sentimiento` el método y el modelo, como ya hace `SentimientoComentario`, para trazar el
   origen de cada resultado.
