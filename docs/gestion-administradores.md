# Gestión de administradores

## Uso y autorización

Ingresar como administrador y abrir **Publicaciones → Gestión de administradores** (también disponible en Dashboard y en el pie de página). Completar nombre de usuario, correo, contraseña inicial y confirmación; presionar **Crear administrador**. El éxito redirige al formulario vacío. La cuenta puede iniciar sesión en el formulario web por nombre de usuario o correo y crear otros administradores.

La ruta `/administradores/` exige sesión y `PERMISOS_PANEL` más `auth.add_user`. GET muestra el formulario; solo POST crea cuentas; otros métodos responden 405. Visitantes se redirigen al login y usuarios sin permisos reciben 403. `is_staff` por sí solo no autoriza. La visibilidad del enlace usa los mismos permisos que la vista.

El backend asigna exclusivamente `Administrador`, `is_active=True`, `is_staff=True` e `is_superuser=False`, sin copiar permisos particulares del creador. Rechaza el alta si el grupo falta o sus permisos difieren de `PERMISOS_ADMINISTRADOR`. El grupo debe estar configurado mediante el mecanismo existente `configurar_roles`; esta funcionalidad no lo modifica automáticamente ni reasigna cuentas históricas.

Dashboard e indicadores de portada ahora usan `PERMISOS_PANEL`, igual que Publicaciones, para que el rol no necesite superusuario. No hay cambios de modelos, migraciones, dependencias, Compose ni configuración.

## Alcance definitivo de permisos

Todos los administradores activos del grupo `Administrador` configurado son equivalentes dentro de TrendWatch: gestión de publicaciones, Dashboard, indicadores y creación de otros administradores. La nueva cuenta recibe ese mismo grupo, sin privilegios directos particulares ni superusuario.

Los superusuarios técnicos de Django conservan privilegios globales adicionales. La gestión de tokens JWT en `/admin/` (`OutstandingToken` y `BlacklistedToken`) no forma parte de la administración normal de TrendWatch y permanece reservada a ellos. Esta decisión está confirmada: no se agregan permisos `token_blacklist` al grupo ni se modifican cuentas existentes.

## Identidad y contraseñas

`AdministradorCreationForm` hereda `UserCreationForm`: normalización de username, validadores del modelo y de contraseña de Django, confirmación y hash mediante `set_password`. Correo obligatorio, validación de formato y longitud; username único sin distinguir mayúsculas. Se reutiliza `errores_identidad` para correos duplicados y cruces username/correo. Los inactivos también reservan su identidad.

La validación y el guardado participan de `serializar_identidad`, con transacción y bloqueo asesor PostgreSQL compartido con registro, perfil y UserAdmin. Como en el mecanismo existente, escritores ORM/SQL externos a ese protocolo pueden eludir las verificaciones adicionales de identidad.

Se mantiene CSRF, los campos de privilegios enviados por HTTP se ignoran y los passwords no se vuelven a mostrar en el formulario. La vista evita caché y marca los parámetros de contraseña como sensibles para los reportes de Django. Los errores de integridad se presentan sin detalles internos. No se encontró un flujo existente de invitación o recuperación para reutilizar: se usa contraseña inicial y no se agregan envío de correo ni autenticación nueva.

## Auditoría mínima y futura integración

Se reutiliza `django.contrib.admin.models.LogEntry`: responsable (`user_id`), fecha/hora (`action_time`), tipo de entidad (`content_type`), cuenta creada (`object_id` y `object_repr`), acción ADDITION y descripción fija del rol. No contiene contraseñas ni hashes.

El alta, la asignación del grupo y el evento se guardan en la misma transacción. Si falla el evento, se revierte la cuenta. El historial del usuario en Django Admin permite consultar ese registro a quienes ya tienen los permisos correspondientes.

El modelo propio `Auditoria` exige una publicación: no se crean noticias ficticias para registrar usuarios. La auditoría general futura deberá integrar/consultar `LogEntry` y definir retención y protección frente a alteraciones; este registro no es un sistema de auditoría inmutable ni cubre modificaciones realizadas por otros flujos. No hay migración pendiente propia de esta funcionalidad.

## Verificación recuperada y cierre

Entorno: imagen local `trendwatch-litoral-web:latest`, Django 6.1.2, Python 3.13 y PostgreSQL/PostGIS 17-3.5 desechable, sin puertos publicados ni volúmenes persistentes. No se usaron bases habituales. Los tests usan hash rápido salvo el flujo de alta/login, que verifica explícitamente PBKDF2.

La pasada dirigida de cierre ejecutó 54 tests y aprobó todos: administración, login/logout, registro normal, perfil, Dashboard, indicadores, navegación e integración del panel. Verificó login de la cuenta nueva por username y email, creación de una tercera cuenta, autorización HTTP, CSRF, validaciones, privilegios manipulados, contraseñas y auditoría transaccional. Evidencia: `/tmp/tw-gestion-cierre.log`.

Además pasó una prueba adicional de igualdad de permisos entre el administrador existente y el nuevo en todos los modelos registrados en Django Admin, y de equivalencia con el superusuario para los modelos `core` y `auth`. Evidencia: `/tmp/tw-gestion-equivalencia-final.log`. Estas dos pasadas cubren 55 pruebas distintas; no se repitieron las 54 para agregar esta comprobación.

La prueba adicional `test_tokens_jwt_reservados_a_superusuarios` aprobó en PostgreSQL aislado tras el traslado: los administradores existente y nuevo carecen de permisos del módulo JWT y reciben 403 por GET y POST en las listas y formularios de alta de ambos modelos de tokens. El superusuario conserva acceso a sus listas. Evidencia: `/tmp/tw-gestion-jwt-cierre.log` (1 prueba, 0.366 s, OK).

En total se conservan 56 pruebas dirigidas distintas aprobadas (54 + equivalencia + JWT). Solo se agregó y ejecutó la prueba JWT en esta etapa: se verificó que el cuerpo de las pruebas anteriores es idéntico, salvo un comentario que documenta la decisión definitiva. El código de producción no cambió y todos sus hashes coinciden con la evidencia preservada antes del traslado.

La comparación diagnóstica inicial detectó dos diferencias preexistentes con el superusuario en los modelos JWT. La decisión funcional definitiva conserva esas diferencias técnicas y exige igualdad entre administradores del grupo.

La comparación completa ya ejecutada sobre la base `235ab7a` conserva esta evidencia válida:

| Versión | Tests | Fallos de aserción | Errores | Omitidos |
| --- | ---: | ---: | ---: | ---: |
| origin/main | 407 | 10 | 1 | 1 |
| Rama, antes de las comprobaciones adicionales de cierre | 416 | 10 | 1 | 1 |

Los bloques de los fallos son idénticos al normalizar únicamente las fechas de captura de las publicaciones. No se repitió esa suite tras cambios limitados a pruebas, documentación y el rótulo del Dashboard.

Fallos preexistentes: `IngestaHistoricaTestCase` de `core.test_clasificacion` (tres fallos y un error), `IngestaRSSClasificadaTestCase` (tres fallos) y cuatro subcasos de `RolesPermisosTestCase.test_update_payloads_validos_conservan_hash_y_no_ejecutan_servicios` por campos derivados del buscador. Logs originales: `/tmp/tw-gestion-base-suite.log` y `/tmp/tw-gestion-suite.log`.

Django no reportó problemas en sus checks durante las pruebas. `git diff --check` pasó. `makemigrations --check --dry-run` propone los mismos cuatro cambios de claves automáticas tanto en main como en la rama: `PublicacionTema`, `TemaTrend`, `UserAuditoria` y `VotoPublicacion`. Es una diferencia preexistente; no se generó ni aplicó esa migración.

Para repetir las pruebas dirigidas con la configuración local de tests:

```bash
python app/manage.py test core.test_gestion_administradores core.test_new_dashboard core.test_indicadores_inicio core.test_auth_views core.test_navegacion_admin core.test_perfil core.test_integracion_pr24 --noinput
```

## Archivos

- Formulario: `app/core/forms.py`.
- Vista y ruta: `app/core/views_administradores.py` (nuevo), `app/core/urls.py`.
- Interfaz: `templates/core/gestion_administradores.html` (nuevo), `core/publicaciones.html`, `core/dashboard.html`, `base.html`, `inicio.html`, bajo `app/core/templates/`. Reutiliza `publication-form.css` sin modificarlo.
- Acceso común a métricas: `app/core/views.py`, `app/core/views_dashboard.py`.
- Pruebas: `app/core/test_gestion_administradores.py` (nuevo), `test_new_dashboard.py`, `test_indicadores_inicio.py`, `test_navegacion_admin.py`.
- Documentación: este archivo, `docs/dashboard-analitico.md`, `docs/PR-gestion-administradores.md` (propuesta local de PR) y las dos capturas.

Capturas Firefox del HTML renderizado por Django con usuario y base en memoria: [escritorio](capturas/administradores/escritorio.png) y [móvil](capturas/administradores/movil.png). Son capturas estáticas sin scripts ni fuentes remotas; no reemplazan las pruebas HTTP y el contenido móvil continúa por debajo del viewport.

## Estado de entrega

Worktree persistente `/home/sebas/Escritorio/trendwatch-gestion-administradores`, trasladado con `git worktree move` desde `/tmp/trendwatch-gestion-administradores`. Los 18 archivos de trabajo existentes conservaron sus hashes SHA-256 tras el traslado. Rama `feat/gestion-administradores`, HEAD `235ab7a`. Cambios sin commit, sin push ni PR. El worktree original conserva `auditorias/` sin seguimiento, sin modificaciones de esta tarea.

El contenedor temporal `tw-gestion-admin-pg` permanece activo con datos en tmpfs y sin volúmenes; no se ejecutaron operaciones destructivas para retirarlo. Los contenedores habituales no se modificaron.

La igualdad entre cuentas del rol se implementa sin elevarlas a superusuario. Los superusuarios técnicos conservan privilegios globales de Django; la revisión encontró que, entre los modelos actualmente registrados en `/admin/`, la gestión de tokens JWT (`OutstandingToken` y `BlacklistedToken`) sigue siendo exclusiva de ellos. Esta diferencia técnica, preexistente en main, está aprobada y queda fuera de la equivalencia del rol de TrendWatch. No hay decisiones funcionales pendientes sobre JWT.


## Preparación del PR

Se actualizó la referencia remota mediante `git fetch origin`: `origin/main` continúa en `235ab7a`, igual que HEAD de la rama. No hay commits nuevos en main ni conflictos de integración que resolver contra esa base. El diff revisado incluye los archivos nuevos, sin credenciales ni archivos auxiliares de `/tmp`. Las contraseñas literales de los tests pertenecen exclusivamente a usuarios generados en la base de pruebas.

La implementación y los estilos usados por las capturas no cambiaron desde su generación; sus hashes se conservaron con el traslado. No fue necesario regenerarlas. La propuesta de título y cuerpo está en [PR-gestion-administradores.md](PR-gestion-administradores.md); no se publicó.


Revisión final: 19 archivos en alcance (12 modificados y 7 nuevos, incluidas dos capturas). `git diff --check` correcto; sin archivos `.env`, bases, logs, bytecode o auxiliares añadidos al worktree. La inspección manual y la búsqueda de patrones comunes de claves privadas/tokens no detectaron secretos. La única contraseña literal añadida es un dato de pruebas aisladas.

La funcionalidad queda lista para revisión del equipo y para autorizar posteriormente commit y publicación del PR, informando los fallos globales preexistentes. No quedan decisiones de permisos pendientes. No se ejecutó commit, push, merge, rebase ni creación de PR.
