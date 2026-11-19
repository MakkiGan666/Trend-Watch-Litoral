# Infraestructura de agrupación editorial (Fase 2A)

Esta fase agrega almacenamiento y revisión administrativa de agrupaciones. No cambia el buscador, el autocompletado, el dashboard ni el pipeline de ingesta. La migración crea tablas nuevas y no completa grupos automáticamente.

## Estados y reglas

- `BORRADOR`: publicaciones candidatas visibles individualmente; nada está vigente.
- `ACTIVO`: sólo después de una aprobación individual explícita de la representante y de cada miembro, además de la aprobación separada del grupo.
- `REVOCADO`: libera las membresías vigentes y conserva el grupo, las decisiones y los eventos.
- Los miembros se comparan siempre directamente contra la representante fija. El servicio requiere evidencia `DUPLICADO_CONFIRMADO` del detector existente y la misma fuente normalizada. No propaga relaciones entre miembros ni permite cobertura entre medios.
- El máximo inicial es 20 publicaciones por grupo. No se almacenan cuerpos editoriales en la evidencia; se guarda una huella SHA-256 para detectar cambios entre revisión y activación.
- El borrador propone una representante determinista: cuerpo completo, metadatos editoriales, referencia de imagen, fecha editorial más reciente y menor ID. Quien aprueba el grupo confirma la representante final. Si la cambia, el servicio vuelve a comparar cada miembro directamente contra ella, reabre todas las decisiones individuales y exige una nueva revisión antes de activar. Una vez aprobado, la representante queda fija.
- Las tablas usan `PROTECT` hacia publicaciones y usuarios. La agrupación nunca edita ni elimina publicaciones ni sus relaciones.

## Permisos

Los permisos de Django se asignan explícitamente a usuarios/grupos:

- `core.revisar_candidatos_editoriales`: crear revisiones y aprobar/rechazar cada publicación con motivo.
- `core.aprobar_agrupacion_editorial`: activar un grupo con motivo, una vez resueltas todas las decisiones.
- `core.revocar_agrupacion_editorial`: revocar un grupo activo con motivo.

La interfaz está bajo el admin de Django, requiere sesión de staff, permisos específicos y POST protegido por CSRF para decisiones. Los modelos de grupo, membresía y evento no ofrecen edición o borrado directo. La lista de eventos es de sólo lectura.

## Integridad y concurrencia

Las operaciones de servicio usan transacciones y bloqueos de fila en orden estable. La base impone una sola fila representante por grupo, una sola pertenencia vigente por publicación, roles/decisiones válidos y que una pertenencia vigente esté aprobada. La activación revalida las huellas y la evidencia directa; las restricciones únicas resuelven carreras que superen la comprobación previa.

La auditoría registra actor, motivo, fecha, decisión y snapshot compacto de evidencia. La migración es aditiva y reversible; al revertir se retiran sólo estas tablas nuevas. Debe hacerse respaldo antes de una reversión operativa porque se perdería el historial de agrupación, no las publicaciones.

La creación es manual por IDs desde el admin; no hay importación automática de candidatos ni aprobación de los 79 grupos del análisis previo. El hash de revisión cubre título, fuente, URL, fecha editorial, cuerpo y referencias de imagen, pero sólo se almacena el hash, no el texto del cuerpo.

## Alcance pendiente

Esta fase no importa ni aprueba los 79 candidatos existentes. Tampoco filtra resultados ni modifica el contrato `total` del buscador. La integración de agrupaciones aprobadas en buscador/API/autocompletado requiere una fase separada, con conteo y paginación por grupo antes de paginar, acceso a cada publicación original y pruebas de contrato.
