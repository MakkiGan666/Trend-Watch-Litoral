# PR #34 — Gestión de administradores y corrección de autorización

Permite crear administradores desde TrendWatch, iniciar sesión con la cuenta nueva y crear otras cuentas del mismo rol. Corrige la escalada confirmada del commit `22bd423`: un administrador podía persistir `is_superuser=True` mediante UserAdmin y agregar permisos técnicos al grupo mediante GroupAdmin.

El alta exige cuenta activa y pertenencia a `Administrador` con los permisos requeridos, o superusuario técnico activo. La vista y los enlaces comparten la política. Permisos equivalentes sin el rol y `is_staff` por sí solos no autorizan.

Django Admin reserva las escrituras de usuarios y grupos, contraseñas ajenas y acciones masivas a superusuarios activos, incluso ante permisos históricos/directos de auth. El administrador conserva consultas y el alta controlada de TrendWatch. Los superusuarios conservan capacidades técnicas y gestión de tokens JWT. El formulario fija el rol sin aceptar privilegios del POST; alta y LogEntry son transaccionales.

## Instalación

No hay migraciones, dependencias ni cambios de Compose. Un operador técnico debe actualizar los grupos con el comando existente `configurar_roles` durante el despliegue autorizado: reemplaza los permisos canónicos conservando los grupos. Hasta hacerlo, el alta falla sin crear cuentas si el grupo tiene el conjunto antiguo. La protección de Django Admin es inmediata al desplegar el código. No se modificaron bases habituales ni cuentas reales. Revisar por separado permisos directos históricos concedidos fuera del rol.

## Validación

- Reproducción HTTP previa con PostgreSQL aislado: el original persistió superusuario propio/ajeno y permisos JWT en el grupo; también aceptó acceso al alta sin pertenecer al rol.
- 82 pruebas dirigidas aprobadas: autorización, permisos históricos, POST manipulado, acciones alternativas/masivas, ausencia de cambios parciales, superusuario legítimo, JWT, CSRF, login, perfil, identidad, navegación, panel, Dashboard e indicadores. Dos altas concurrentes de la misma identidad confirman sólo una cuenta y un LogEntry.
- Suite completa repetida: **main 407 pruebas; rama 429; ambas con 10 fallos, un error y una omisión**. Los once bloques coinciden normalizando fechas, líneas e IDs de fixtures. Fallos preexistentes en clasificación/ingesta y campos derivados del buscador; ninguna regresión nueva detectada. La suite completa no pasa.
- Checks Django sin incidencias; `git diff --check` correcto. Sin cambios de modelos ni migraciones aplicadas.

Evidencia, permisos definitivos y riesgos: [gestion-administradores.md](gestion-administradores.md). Los logs detallados locales están identificados allí. Las capturas existentes ilustran el formulario: [escritorio](capturas/administradores/escritorio.png), [móvil](capturas/administradores/movil.png).

## Límites y estado

`LogEntry` no es inmutable; escritores ORM/SQL externos pueden eludir el protocolo de identidad. La normalización automática de cuentas históricas queda fuera del alcance. No se encontraron otras vías de escalada en las rutas de cuentas revisadas; esto no constituye una auditoría general del repositorio.

Recomendación de la auditoría correctiva: **Aprobado con observaciones**, por configuración operativa pendiente y fallos globales preexistentes. Mantener **Draft**, sin merge; las pruebas dirigidas no declaran el PR listo para integrar.
