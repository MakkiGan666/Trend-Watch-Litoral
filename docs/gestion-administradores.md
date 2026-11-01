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

## Verificación final de integración — 2026-11-01 UTC

Esta sección actualiza el dictamen anterior. Tras `git fetch origin`, el PR #34 seguía abierto, Draft y fusionable, con HEAD `6c838d2b8329e6f85449896acdd84986010d0014`. El worktree estaba limpio, sin cambios de terceros. `origin/main` continuaba en `235ab7a521782c0f2f4d2cd3619f5dab96a71ff6` y es ancestro del HEAD: no hay cambios de main pendientes de incorporar ni hace falta simular un merge adicional. GitHub no informó estados de CI; esto no equivale a CI aprobada.

### Instalación histórica aislada

Se creó exclusivamente para esta tarea `tw-pr34-final-20261101`, ID inicial `c2ef75a77d2b`, imagen `postgis/postgis:17-3.5`, etiqueta `trendwatch.task=pr34-final-20261101`, sin puertos publicados, con `--network none` y sin montar datos del equipo. PostgreSQL usa autenticación trust **solamente en este entorno sintético aislado**. La base `pr34_upgrade` se migró con el código exportado de main antes de ejecutar código del PR. Los runners comparten únicamente la red de ese contenedor y montan el código de sólo lectura. No se reutilizó `tw-gestion-admin-pg` ni ninguna base habitual. El recurso nuevo se conserva para inspección; no se realizaron limpiezas destructivas.

Estado inicial: cinco cuentas Django (un superusuario técnico, dos administradores, un lector y una cuenta staff con permisos equivalentes individuales); grupos `Administrador`, `Usuario` y `HistoricoAdicional`; permisos antiguos de auth, incluidos `change_user` y `change_group`; el segundo administrador pertenece a tres grupos y tiene permisos individuales. Se agregaron un registro de ingesta, tres publicaciones, tres comentarios, tres guardados, tres valoraciones y un LogEntry previo. Todas las identidades y contraseñas son sintéticas. El snapshot registra filas y relaciones; sustituye cada hash de contraseña por su huella SHA-256. Las contraseñas de este escenario usan el hasher predeterminado, sin sustituirlo por MD5.

Resultados del comando sin opciones:

- `Administrador`: exactamente 41 permisos canónicos; `Usuario`: exactamente `core.view_publicacion`. Desaparecen del primer grupo las escrituras técnicas antiguas de usuarios y grupos.
- Conserva IDs de grupos, todas las cuentas y sus flags, huellas de hashes, permisos individuales, pertenencias múltiples, contenido, relaciones y auditoría previa. Se verificó además cada contraseña sintética mediante `check_password`.
- La segunda ejecución no cambia ninguna fila observada. Un intento con `--usuario` inexistente provoca `CommandError` y revierte también los cambios de grupos realizados antes del error.
- **Grupos y usuarios tienen efectos diferentes**: el comando sin opciones reemplaza permisos de ambos grupos; no cambia `is_staff`, `is_active`, `is_superuser`, contraseñas, otros grupos ni permisos individuales. No recupera por sí solo una cuenta histórica inactiva o sin la configuración staff esperada.
- Los permisos individuales y los concedidos por otros grupos siguen sumándose. El administrador con permisos auth históricos continúa bloqueado para escribir usuarios/grupos en Django Admin, pero otros permisos técnicos, por ejemplo JWT concedidos fuera del rol, necesitan revisión: quitar permisos del grupo canónico no los revoca. La prueba no afirma que un usuario con permisos JWT directos pierda ese acceso.

### HTTP, seguridad y auditoría

Django Client ejecutó solicitudes mediante el enrutamiento y middleware de Django contra `pr34_upgrade`; no se utilizó un servidor web externo. Ambos administradores históricos iniciaron sesión y accedieron a Publicaciones, Dashboard, portada con indicadores y Gestión; cada uno creó una cuenta, y el superusuario también. Se rechazaron con 403 cambios de usuarios propios/ajenos, contraseñas ajenas, grupos y acciones masivas; no hubo elevación de flags ni alteraciones históricas. Los administradores sin concesiones JWT externas recibieron 403 en las listas de tokens; el superusuario obtuvo 200. Lector y staff con permisos individuales equivalentes recibieron 403 en GET/POST del alta, sin cambios parciales.

Los tres eventos nuevos identifican responsable, cuenta creada, acción ADDITION y fecha dentro del intervalo de la solicitud, sin contraseña ni hash. La inyección de `IntegrityError` en auditoría revierte íntegramente cuenta y relaciones para los tres actores; el evento previo se conserva. Las 82 pruebas dirigidas complementan el escenario con CSRF, formularios manipulados, altas encadenadas/concurrentes, operaciones técnicas legítimas del superusuario y rutas alternativas JWT/API. No se agregó otro sistema de auditoría.

### Regresión y checks repetidos

| Versión / comprobación | Resultado nuevo |
| --- | --- |
| main `235ab7a`, suite core | 407 pruebas; 10 fallos, 1 error, 1 omisión |
| PR `6c838d2`, suite core | 429 pruebas; 10 fallos, 1 error, 1 omisión |
| Suite dirigida del PR | 82 pruebas, OK, sin omisiones |
| Escenario sobre instalación histórica | `INTEGRACION_OK` |
| `manage.py check`, ambas versiones | OK |
| `makemigrations --check --dry-run`, ambas versiones | Salida 1; misma propuesta preexistente |
| `git diff --check` | OK |

Los once bloques de fallo/error coinciden tras normalizar exclusivamente fechas `datetime`, conteos `[N chars]` y longitud del diff de la aserción. Persisten los fallos de clasificación/ingesta y actualización de campos derivados del buscador; no se detectaron regresiones adicionales. La suite completa **sigue sin aprobar**. Ambas suites usaron la misma imagen local y servidor PostgreSQL, bases de test diferentes y el mismo hasher rápido sólo para datos sintéticos de los tests. Django creó y destruyó exclusivamente esas bases de test.

La propuesta idéntica de migración `0012_alter_publicaciontema_id_alter_tematrend_id_and_more.py` afecta los campos `id` de `PublicacionTema`, `TemaTrend`, `UserAuditoria` y `VotoPublicacion`. Los modelos, migraciones y `configurar_roles.py` no tienen diff entre main y el PR. No se generó ni aplicó esa migración; queda fuera de esta integración.

Evidencia local nueva: `/tmp/pr34-final/seed.log`, `baseline.json`, `upgrade.log`, `branch-suite.log`, `main-suite.log`, `directed.log`, `branch-check.log`, `main-check.log`, `branch-migrations.log`, `main-migrations.log`, `exit-codes.json` y `failure-comparison.diff` (vacío). Es evidencia temporal del equipo, no un artefacto de CI ni datos de producción.

### Reproducción

Los scripts usados están en [`tools/gestion_administradores/`](../tools/gestion_administradores/). `runner.py` configura exclusivamente PostgreSQL local al namespace del contenedor, base sintética `pr34_upgrade`, host de tests y una clave sintética. `scenario.py` tiene fases `TW_SCENARIO=seed` y verificación (predeterminada). La carga se niega a continuar si ya existen cuentas. El runner sólo debe ejecutarse dentro del contenedor de pruebas indicado, nunca contra una instalación habitual.

En un directorio temporal nuevo:

1. Crear un contenedor con nombre exclusivo; los scripts de esta ejecución esperan `tw-pr34-final-20261101`. Si ya existe, **no reutilizarlo automáticamente**: comprobar su pertenencia o adaptar los nombres de los scripts para una nueva ejecución. Usar la imagen PostGIS indicada, etiqueta de tarea, `--network none`, `POSTGRES_DB=pr34_upgrade` y `POSTGRES_HOST_AUTH_METHOD=trust`; sin puertos publicados.
2. Preparar `/tmp/pr34-final/main` con `git archive 235ab7a521782c0f2f4d2cd3619f5dab96a71ff6 app | tar -x -C /tmp/pr34-final/main`. Copiar los scripts `runner.py` y `scenario.py` al directorio de evidencia. No copiar `.env`.
3. Ejecutar `migrate --noinput` con el código exportado de main; luego `scenario` con `TW_SCENARIO=seed`, registrando stdout en `/tmp/pr34-final/seed.log`.
4. Ejecutar `python3 -B tools/gestion_administradores/run_checks.py`. Extrae `baseline.json` de la carga, verifica la actualización, ejecuta ambas suites y la dirigida, y los checks. `TW_EVIDENCE_ROOT` permite cambiar el directorio de evidencia (con estructura `main/app`); la imagen esperada es `trendwatch-litoral-web:latest`, ya disponible localmente. Los códigos de salida quedan en `exit-codes.json`; el script no convierte fallos conocidos en aprobación.

Plantilla de invocación Docker de los pasos 3 y 4 (sustituir `CODIGO` por la ruta absoluta de `main/app` o `app` y `COMANDO` por los argumentos indicados):

```bash
docker run --rm --network container:tw-pr34-final-20261101 --read-only --tmpfs /tmp \
  -v CODIGO:/app:ro -v /tmp/pr34-final/runner.py:/runner.py:ro \
  -v /tmp/pr34-final:/evidence:ro --entrypoint python \
  trendwatch-litoral-web:latest -B /runner.py COMANDO
```

Para la carga, añadir `-e TW_SCENARIO=seed` antes de los montajes. La plantilla no inicia ni toca servicios de Compose. No eliminar recursos por coincidencia parcial de nombre.

### Procedimiento operativo de despliegue y recuperación

1. Confirmar el commit revisado, la base de destino y el entorno; tener un superusuario técnico activo con acceso administrativo y una copia de seguridad verificada. Registrar de forma protegida permisos de grupos, pertenencias, permisos individuales y flags históricos; no publicar credenciales ni hashes. Revisar excepciones y quién debe conservar privilegios técnicos.
2. Desplegar el código corregido y verificar migraciones ya requeridas por la instalación. `configurar_roles` necesita tablas y todos los permisos canónicos creados por `migrate`/`post_migrate`, y conexión con capacidad de escribir grupos/permisos. No genera ni aplica migraciones. Coordinar una ventana sin cambios concurrentes de roles y con el alta temporalmente no disponible: si los grupos conservan permisos antiguos, la vista rechaza el alta sin persistirla.
3. Ejecutar en el servicio y base verificados `python manage.py configurar_roles`, **sin `--usuario` ni `--rol`** para actualizar sólo grupos. Revisar errores y salida antes de reabrir el alta.
4. Verificar conjuntos exactos, acceso de los administradores, denegación de escrituras técnicas/JWT para el rol, acceso técnico del superusuario y un alta autorizada con LogEntry. Comparar recuentos e integridad histórica y repetir el comando para confirmar idempotencia. Usar sesiones nuevas al comprobar permisos.
5. Si se requiere normalizar una cuenta histórica, revisar y autorizar cada caso. La operación existente `python manage.py configurar_roles --usuario NOMBRE --rol Administrador` **reemplaza todos sus grupos**, limpia todos sus permisos individuales y fija `is_staff=True`; con `--rol Usuario` fija `is_staff=False`. Rechaza superusuarios y no cambia contraseña ni activa cuentas. Puede quitar permisos legítimos ajenos al rol: no ejecutarla masivamente ni asumir que equivale al comando sin opciones. No se ejecutó sobre cuentas reales.

Si el comando falla antes de confirmar su transacción, sus escrituras se revierten; verificar el estado en una conexión nueva antes de reintentar. Corregir la causa (por ejemplo, permisos faltantes o conexión) y repetir. Si la operación ya confirmó o se modificaron cuentas con opciones, **no existe un undo automático**: recuperar selectivamente desde la captura previa bajo control técnico, evaluando cambios posteriores. No restaurar toda la base ni volver al código vulnerable como respuesta automática. Restaurar permisos antiguos vuelve a impedir el alta por igualdad canónica y puede ampliar accesos; requiere una decisión técnica explícita. No se ensayó recuperación sobre datos reales.

**Dictamen actualizado: Aprobado con observaciones.** Recomiendo pasar de Draft a Ready for review. Considero técnicamente seguro autorizar el merge del alcance revisado si se acepta explícitamente la deuda preexistente de suite/migraciones y se aplica el procedimiento de roles y revisión de excepciones. No es una aprobación global del repositorio ni una garantía sobre permisos técnicos externos al rol. No se fusionó ni se cambió el estado Draft del PR.
