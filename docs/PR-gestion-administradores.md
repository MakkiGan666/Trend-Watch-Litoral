# PR #34 — Gestión de administradores y corrección de autorización

Al integrarla con la rama de frontend, Dashboard y los indicadores de Inicio se conservan exclusivos de superusuarios, según la decisión previa del equipo. Los resultados de pruebas y del escenario histórico descritos abajo corresponden a la PR #34 original; la integración se verifica por separado.

Permite crear administradores desde TrendWatch, iniciar sesión con la cuenta nueva y crear otras cuentas del mismo rol. Corrige la escalada confirmada del commit `22bd423`: un administrador podía persistir `is_superuser=True` mediante UserAdmin y agregar permisos técnicos al grupo mediante GroupAdmin.

El alta exige cuenta activa y pertenencia a `Administrador` con los permisos requeridos, o superusuario técnico activo. La vista y los enlaces comparten la política. Permisos equivalentes sin el rol y `is_staff` por sí solos no autorizan.

Django Admin reserva las escrituras de usuarios y grupos, contraseñas ajenas y acciones masivas a superusuarios activos, incluso ante permisos históricos/directos de auth. El administrador conserva consultas y el alta controlada de TrendWatch. Los superusuarios conservan capacidades técnicas y gestión de tokens JWT. El formulario fija el rol sin aceptar privilegios del POST; alta y LogEntry son transaccionales.

## Instalación

No hay migraciones, dependencias ni cambios de Compose. Un operador técnico debe actualizar los grupos con el comando existente `configurar_roles` durante el despliegue autorizado: reemplaza los permisos canónicos conservando los grupos. Hasta hacerlo, el alta falla sin crear cuentas si el grupo tiene el conjunto antiguo. La protección de Django Admin es inmediata al desplegar el código. No se modificaron bases habituales ni cuentas reales. Revisar por separado permisos directos históricos y pertenencias múltiples: el comando sin opciones no los elimina ni cambia flags de las cuentas. La variante con `--usuario` reemplaza todos los grupos, limpia permisos individuales y cambia `is_staff`; requiere revisión individual y no debe usarse como actualización masiva.

## Validación

- Reproducción HTTP previa con PostgreSQL aislado: el original persistió superusuario propio/ajeno y permisos JWT en el grupo; también aceptó acceso al alta sin pertenecer al rol.
- 82 pruebas dirigidas aprobadas: autorización, permisos históricos, POST manipulado, acciones alternativas/masivas, ausencia de cambios parciales, superusuario legítimo, JWT, CSRF, login, perfil, identidad, navegación, panel, Dashboard e indicadores. Dos altas concurrentes de la misma identidad confirman sólo una cuenta y un LogEntry.
- Suite completa repetida: **main 407 pruebas; rama 429; ambas con 10 fallos, un error y una omisión**. Los once bloques coinciden normalizando fechas, líneas e IDs de fixtures. Fallos preexistentes en clasificación/ingesta y campos derivados del buscador; ninguna regresión nueva detectada. La suite completa no pasa.
- Verificación final repetida desde `6c838d2` contra main actualizado `235ab7a`: mismos resultados de 407/429 pruebas y 82 dirigidas aprobadas. Los once bloques de fallo/error coinciden tras normalizar fechas y longitudes de representación. Sin regresiones nuevas detectadas.
- Instalación histórica simulada desde main en PostgreSQL/PostGIS nuevo `tw-pr34-final-20261101`, base `pr34_upgrade`: cinco cuentas sintéticas, permisos auth antiguos, permisos individuales, pertenencias múltiples, publicaciones y relaciones, auditoría previa. `configurar_roles` deja exactamente 41 permisos de Administrador y uno de Usuario; conserva cuentas, hashes, flags, datos y relaciones; es idempotente. Un error provocado revierte los cambios de grupos.
- HTTP sobre esa base: acceso y altas por ambos administradores históricos y el superusuario; denegaciones técnicas sin elevación ni pérdida de datos. Auditoría con responsable, cuenta, fecha y ADDITION, sin secretos; fallo inyectado revierte cada alta.
- `check` y `git diff --check`: OK. `makemigrations --check --dry-run`: salida 1 en ambas versiones con la misma propuesta preexistente para los cuatro campos `id` de tablas de relaciones; no se generaron migraciones.
- main es ancestro del HEAD; PR fusionable, sin commits remotos nuevos al iniciar. Sin estados de CI informados por GitHub.

Evidencia, permisos definitivos y riesgos: [gestion-administradores.md](gestion-administradores.md). Los logs detallados locales están identificados allí. Las capturas existentes ilustran el formulario: [escritorio](capturas/administradores/escritorio.png), [móvil](capturas/administradores/movil.png).

## Límites y estado

`LogEntry` no es inmutable; escritores ORM/SQL externos pueden eludir el protocolo de identidad. La normalización automática de cuentas históricas queda fuera del alcance. No se encontraron otras vías de escalada en las rutas de cuentas revisadas; esto no constituye una auditoría general del repositorio.

Dictamen de la verificación final: **Aprobado con observaciones**. Se recomienda pasar a **Ready for review** y se considera técnicamente seguro autorizar su merge para el alcance revisado, condicionado a aceptar la deuda preexistente de suite/migraciones y aplicar el procedimiento documentado de actualización de roles y revisión de permisos externos. El comando no revoca permisos JWT concedidos individualmente o por otros grupos. No hay undo automático tras confirmar; recuperación selectiva desde captura previa bajo control técnico. El PR permanece Draft y no se fusionó.

Escenario reproducible: [`tools/gestion_administradores/`](../tools/gestion_administradores/). Evidencia temporal nueva: `/tmp/pr34-final/`; procedimiento completo, requisitos, límites y recuperación en [gestion-administradores.md](gestion-administradores.md#verificación-final-de-integración--2026-11-01-utc). Sólo se modificaron documentación y herramientas de verificación, sin código de producción.
