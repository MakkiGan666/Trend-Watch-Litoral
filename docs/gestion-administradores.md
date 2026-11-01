# Gestión de administradores y auditoría correctiva del PR #34

## Uso y política definitiva

Ingresar con el rol Administrador y abrir **Publicaciones → Gestión de administradores**, también disponible en Dashboard, portada y pie de página. La cuenta creada puede iniciar sesión por usuario o correo y crear otros administradores.

`/administradores/` exige una cuenta activa que sea superusuario técnico, o pertenezca al grupo `Administrador` y tenga `PERMISOS_PANEL` más `auth.add_user`. Tener permisos directos equivalentes, pertenecer a otro grupo o tener `is_staff=True` no sustituye esa pertenencia. La vista y los cuatro enlaces usan `puede_gestionar_administradores`; el template tag sólo controla presentación, la vista vuelve a autorizar en el servidor.

GET presenta el formulario, POST crea, los demás métodos devuelven 405. Visitantes e inactivos se redirigen al login; cuentas autenticadas no autorizadas reciben 403.

| Capacidad | Administrador de TrendWatch | Superusuario técnico activo |
| --- | --- | --- |
| Publicaciones, Dashboard, indicadores, scraping e IA según permisos canónicos | Sí | Sí |
| Crear administradores desde TrendWatch | Sí, con rol y permisos requeridos | Sí |
| Consultar usuarios y grupos en Django Admin | Sí, con `is_staff` | Sí, con `is_staff` |
| Crear, editar, eliminar usuarios/grupos en Django Admin; cambiar contraseñas ajenas | No | Sí |
| Asignar privilegios, permisos directos o grupos desde Django Admin | No | Sí |
| Administración de tokens JWT | No recibe permisos | Conserva privilegios globales |

Los permisos canónicos conservan el CRUD de los modelos de contenido ya incluidos en `MODELOS_ADMIN`, `core.ejecutar_scraping`, `core.procesar_ia`, `auth.view_user`, `auth.view_group` y `auth.add_user`. Este último habilita el alta controlada de TrendWatch; por sí solo no habilita escrituras en Django Admin. Las restricciones de integridad ya existentes sobre contenido permanecen.

Todos los miembros del rol canónico tienen las mismas capacidades administrativas. Esa igualdad no incluye los privilegios globales de Django ni permisos particulares otorgados fuera del rol por operadores técnicos.

## Hallazgos y reproducción previa a las correcciones

Commit auditado: `22bd423dcb1b83d95e508ecaf1fa53d90ce2adf5`. Base comparada: `origin/main`, `235ab7a521782c0f2f4d2cd3619f5dab96a71ff6`. PR abierto y Draft al iniciar. Ejecución: 2026-11-01 UTC (2026-10-31 en Argentina).

**AUD-34-01, P1 confirmado.** El grupo recibía CRUD de usuarios y grupos; `UsuarioAdmin` heredaba los permisos y formularios de `UserAdmin` sin una frontera técnica. Pruebas HTTP con Django Client contra PostgreSQL aislado demostraron:

- POST válido a `/admin/auth/user/<id>/change/`, con campos requeridos de fecha y `is_superuser=on`, persistió `is_superuser=True` tanto para otro usuario como para el propio administrador. Se prueba primero otro usuario para evitar que la segunda comprobación dependa de una escalada previa.
- POST a `/admin/auth/group/<id>/change/` persistió permisos de `token_blacklist` en `Administrador`.
- Las aserciones defensivas `assertFalse(usuario.is_superuser)` y ausencia de permisos JWT fallaron en el original: dos tests, tres fallos de subcasos/asercciones. Log: `/tmp/aud34-canonical-repro.log`.

**AUD-34-02, P2 confirmado.** Una cuenta fuera de `Administrador`, con los permisos del grupo asignados directamente, obtuvo GET 200 en el alta en lugar de 403. La prueba inicial se detuvo allí; la nueva regresión comprueba también POST, ausencia de cuenta creada y enlace oculto. Log previo: `/tmp/aud34-repro.log`.

**AUD-34-03, P2 confirmado.** Las pruebas anteriores comprobaban privilegios manipulados del formulario propio y JWT, pero no las escrituras de `UserAdmin`/`GroupAdmin`. La comparación anterior con superusuarios para `auth` asumía una igualdad incompatible con la política definitiva.

No se descartó ninguno de los tres hallazgos. Ocultar enlaces o campos no mitigaba el P1.

## Correcciones de backend

`EscrituraTecnicaMixin` reserva `has_add_permission`, `has_change_permission` y `has_delete_permission` de usuarios y grupos a superusuarios activos. También rechaza POST sobre sus listas, incluidas acciones masivas. `UserAdmin` comprueba `has_change_permission` en la ruta alternativa de contraseña. Los formularios completos siguen disponibles para el superusuario; se conservan las validaciones y el bloqueo de identidad existentes.

El control se aplica incluso si la instalación conserva los antiguos permisos del grupo o si se asignaron permisos directos de `auth`. Se eliminaron del conjunto canónico las escrituras de grupos y los cambios/borrados de usuarios, conservando consultas y el permiso requerido por el alta propia. La creación desde TrendWatch sigue fijando `is_active=True`, `is_staff=True`, `is_superuser=False` y exclusivamente el grupo canónico, ignorando privilegios enviados por HTTP.

No hay cambios de modelos, migraciones, dependencias ni Docker Compose. El test histórico de `core.tests.RolesPermisosTestCase` ahora exige sólo consulta de usuarios/grupos para el administrador de aplicación, conforme a esta decisión funcional.

## Configuración sobre una instalación existente

El comando existente `python manage.py configurar_roles` usa `permissions.set()` y reemplaza los permisos antiguos de ambos grupos conservando sus identidades. Una prueba parte de todos los permisos asignados al grupo, ejecuta el comando y verifica el conjunto exacto, sin `change_group`. La suite también conserva pruebas de idempotencia y asignación por comando.

Un operador técnico deberá ejecutarlo en su instalación durante el despliegue autorizado, tras revisar su configuración. **No se ejecutó sobre bases habituales en esta auditoría.** Hasta actualizar el grupo, el alta de TrendWatch falla sin crear cuentas porque exige igualdad con el conjunto canónico nuevo. Los controles de Django Admin protegen desde que se despliega el código, incluso antes de actualizar roles. El comando sin `--usuario` no limpia permisos directos ni otros grupos de cuentas históricas; corresponde revisarlos técnicamente si existen. No se modifican cuentas reales automáticamente.

## Identidad, CSRF y auditoría

El formulario hereda `UserCreationForm`, valida identidad, correo y contraseñas, guarda hash y no vuelve a mostrar passwords. `serializar_identidad` mantiene una transacción con bloqueo asesor PostgreSQL compartido con registro, perfil y UserAdmin. El alta, la relación de grupo y `LogEntry` se confirman juntos; si falla la auditoría se revierte todo. El evento registra responsable, fecha, cuenta y acción, sin contraseña ni hash.

La revisión acotada encontró que registro normal crea usuarios con `create_user` sin copiar flags; perfil admite sólo datos personales y guarda columnas específicas bajo bloqueo; `UserMeView` sólo implementa GET. No hay una API de escritura genérica de usuarios en las rutas actuales. Se conservaron CSRF y las restricciones JWT existentes. La regresión verifica POST/PUT/PATCH/DELETE autenticados de `/api/auth/me/` con 405.

La prueba concurrente realiza dos POST con la misma identidad en conexiones PostgreSQL independientes: uno confirma (302), el otro muestra errores (200); queda una cuenta y un `LogEntry`. Los tests de identidad/perfil cubren además carreras con registro, cambios de email y contraseña.

## Validación final

Todos los tests se ejecutaron en el contenedor temporal `tw-gestion-admin-pg`, sin volúmenes montados, con bases `test_aud34_*` creadas y destruidas por Django. El código se montó de sólo lectura en la imagen local `trendwatch-litoral-web:latest`. No se alteraron contenedores habituales, cuentas reales, secretos ni `.env`; las llamadas de scraping/IA de las suites usan sus mocks existentes.

Comando dirigido (con configuración de PostgreSQL aislada):

```bash
python manage.py test core.test_gestion_administradores core.test_new_dashboard core.test_indicadores_inicio core.test_auth_views core.test_navegacion_admin core.test_perfil core.test_integracion_pr24 core.test_identidad --noinput
```

Resultados finales:

| Versión | Pruebas | Fallos | Errores | Omitidos |
| --- | ---: | ---: | ---: | ---: |
| `origin/main` (`235ab7a`) | 407 | 10 | 1 | 1 |
| Rama corregida | 429 | 10 | 1 | 1 |
| Regresión dirigida corregida | 82 | 0 | 0 | 0 |

Logs locales: `/tmp/aud34-main.log`, `/tmp/aud34-suite.log`, `/tmp/aud34-directed.log`. Los once bloques de fallos/error coinciden tras normalizar fechas `datetime`, números de línea y IDs de publicaciones/registros de fixtures; `/tmp/aud34-comparacion.diff` queda vacío. Los nombres y subcasos coinciden sin normalización.

Persisten tres fallos y un error de `IngestaHistoricaTestCase`, tres fallos de `IngestaRSSClasificadaTestCase` y cuatro subcasos de actualización de publicaciones por campos derivados del buscador. No hay regresiones nuevas detectadas. **La suite completa no pasa.** Los checks Django incluidos en ambas suites no reportaron incidencias y `git diff --check` pasó. No se generaron ni aplicaron migraciones.

La primera pasada dirigida descubrió dos rechazos de acciones masivas que respondían 200 sin ejecutar la acción; el backend ahora los rechaza con 403. La primera suite general detectó una expectativa histórica incompatible con la política nueva y una prueba API autenticada incorrectamente con sesión; se corrigieron y se repitieron ambas suites completas de la rama. Los resultados de la tabla corresponden al estado final.

Las pruebas de autorización HTTP y persistencia están separadas de `test_visibilidad_y_administrador_sin_superusuario`. Cubren alta y login por usuario/correo, tercer administrador, equivalencia de permisos, CSRF, rechazo sin cambios parciales (incluidas relaciones de grupos/permisos), escrituras alternativas y masivas, privilegios históricos, usuario normal, usuario sin rol con permisos, miembro sin permisos, inactivos y operaciones técnicas del superusuario.

## Riesgos residuales y límites

`LogEntry` no es inmutable y no registra escritores ORM/SQL externos. El bloqueo de identidad protege escritores participantes, no SQL arbitrario. Los superusuarios y operadores con acceso a la base siguen siendo autoridades técnicas. Un permiso técnico concedido directamente fuera del rol requiere revisión operativa; no se normalizan automáticamente cuentas históricas. La suite general mantiene problemas ajenos a esta corrección; pasar pruebas dirigidas no declara el PR listo para merge.

Las capturas [escritorio](capturas/administradores/escritorio.png) y [móvil](capturas/administradores/movil.png) ilustran el formulario existente; esta corrección modifica autorización y visibilidad, sin rediseñar la interfaz. No sustituyen las pruebas HTTP. No se fusiona el PR; se mantiene Draft.
