# Fase 3C — Detección editorial incremental en sombra

## Alcance

La detección se ejecuta sólo para publicaciones recién insertadas por el
pipeline RSS multifuente. No recorre el catálogo histórico ni analiza los 93
candidatos ya guardados en cada ciclo. La salida son candidatos de revisión en
sombra; esta integración no crea, aprueba, activa, revoca ni oculta grupos.

El circuito legacy independiente de El Territorio no llama a esta ruta y queda
sin cambios. Las publicaciones, sus relaciones y las agrupaciones vigentes se
conservan.

## Flujo y recuperación

1. `persistencia_multifuente._guardar` inserta la publicación y, si el gate
   `DETECCION_EDITORIAL_SOMBRA_MULTIFUENTE_HABILITADA` está activo, crea en la
   misma transacción un `TrabajoDeteccionSombraEditorial` de estado `PENDIENTE`.
   Si no se puede guardar el outbox, se revierte esa publicación individual;
   el lote conserva el aislamiento por noticia.
2. Al terminar el ciclo normal, `planificador_multifuente.ejecutar_ciclo`
   consume hasta 50 outbox pendientes. No requiere una nueva consulta RSS para
   retomar un trabajo pendiente; el worker existente lo vuelve a intentar en
   el siguiente ciclo.
3. Cada publicación nueva se compara únicamente con filas de la misma fuente
   y fecha editorial dentro de ±2 días. El índice
   `Publicacion(fuente, fecha_publicacion)` acota la búsqueda. Se inspeccionan
   como máximo 250 comparables; si se excede, el trabajo pasa a
   `REVISION_MANUAL`.
4. El detector existente decide si hay un par directo. Se filtran pares que
   no incluyan la publicación recién procesada y se delega la persistencia al
   servicio H5.10. La llamada incremental no reconcilia la cola histórica.
5. El outbox se marca `COMPLETADO` junto con la escritura de candidatos en una
   transacción. Ante error, la transacción revierte, el trabajo permanece
   pendiente y aumenta un contador. Tras tres fallos pasa a `REVISION_MANUAL`.

Los consumidores bloquean la fila con `SELECT FOR UPDATE SKIP LOCKED`. Dos
workers no procesan simultáneamente el mismo trabajo. La unicidad por
publicación del outbox y la clave idempotente (par/versionado del detector) de
la cola de candidatos evitan duplicados por reintentos. No se utiliza
transitividad: cada par requiere evidencia directa del detector.

## Esquema

La migración aditiva `0033_deteccion_sombra_multifuente`:

- Crea `core_trabajo_deteccion_sombra_editorial`, con una fila por publicación
  nueva, estado, intentos, cantidad de candidatos, código de error acotado y
  marcas de tiempo.
- Agrega el índice compuesto de fuente y fecha editorial para la consulta
  incremental.
- No actualiza ni rellena trabajos para publicaciones existentes.
- No cambia las tablas de publicaciones, candidatos o agrupaciones fuera del
  índice nuevo.

Estados del outbox: `PENDIENTE`, `COMPLETADO` y `REVISION_MANUAL`. Durante la
evaluación la fila se mantiene bloqueada dentro de una transacción; si el
proceso muere, PostgreSQL revierte el cambio y la fila sigue pendiente.

## Gates y operación

El gate nuevo se define como variable de entorno
`DETECCION_EDITORIAL_SOMBRA_MULTIFUENTE_HABILITADA`, cuyo valor por defecto es
falso. Con el gate cerrado no se crean outbox y no cambia la salida habitual
del planificador. Abrirlo sólo habilita registro y consumo de candidatos en
sombra; no habilita fuentes, no arranca el worker, no ejecuta scraping ni IA,
y no habilita `AGRUPACION_EDITORIAL_AUTOMATICA_HABILITADA`.

La automatización editorial automática existente conserva su propio gate,
cerrado por defecto. No ejecutar `agrupar_duplicados_editoriales --aplicar`
como parte de esta función. El worker continúa requiriendo inicio explícito y
programaciones aprobadas; no se inicia al levantar Django.

## Evidencia técnica de las 11 fuentes seleccionadas

La validación técnica conservada en
`/home/sebas/Documentos/TrendWatch/validaciones/ETAPA5-ingesta-multifuente-20261117.md`
procesó una muestra real por fuente en PostgreSQL aislado. Los 11 casos
obtuvieron los campos del extractor, fueron persistidos y reprocesados sin
duplicar. Fue QA temporal, no autorización de conservar o exhibir artículos.
La revisión posterior de acceso en
`/home/sebas/Documentos/TrendWatch/validaciones/ETAPA7B-configuracion-operativa-multifuente-20261118.md`
es más reciente respecto de robots.txt y registró seis respuestas 403. No se
repiten solicitudes a esos hosts.

| Fuente | Evidencia técnica retenida | Robots/impedimento más reciente | Reutilización de cuerpo completo | Activable ahora |
|---|---|---|---|---|
| Noticias del 6 | Una extracción real | 200; feed/artículo permitidos en esa revisión | Permiso del titular no acreditado | No |
| Norte Misionero | Una extracción real | 200; sin demora explícita observada | No se acreditó licencia de almacenamiento/exhibición | No |
| Noticias de la Calle | Una extracción real | 403; detener y no reintentar | RSS oficial describe titulares/sumarios; no acredita cuerpo completo | No |
| Stop en Línea | Una extracción real; cuerpo corto revisado | 403; detener y no reintentar | No resuelta | No |
| Misiones Online | Una extracción real; título HTML varía del RSS | 403 y términos restrictivos a extracción/reproducción sistemática | Requiere aclaración/autorización apropiada | No |
| INFOBER | Una extracción real; muestra breve | 200; rutas ordinarias permitidas en la revisión | No se encontró licencia para cuerpos | No |
| OberaOnline | Una extracción real | 200; sin demora explícita observada | No se encontró licencia para cuerpos | No |
| E24N | Una extracción real | 200; señales `use=reference`, `ai-train=no` | Señales no conceden el uso completo previsto; respetar no entrenamiento | No |
| Radio Yguazú | Una extracción real; fecha derivó de RSS | 403; detener y no reintentar | No resuelta | No |
| La Misión Digital | Una extracción real | 403; detener y no reintentar | Derechos/uso no resueltos | No |
| Iguazú Ahora | Una extracción real | 403; detener y no reintentar | No resuelta | No |

Las 7 fuentes restantes del catálogo (Primera Edición, Oberá Inside, Eldorado
Noticias, La Voz de Cataratas, Alem News, Fracrán Noticias y Noticias de
Irigoyen) no fueron parte de la selección ni de la prueba de 11; no hay en esos
informes evidencia suficiente para clasificarlas como técnicamente validadas.
El Territorio es una fuente histórica fuera del catálogo RSS multifuente y su
circuito legacy permanece independiente.

La evidencia de robots informa sobre el rastreo técnico, no sobre derechos de
almacenamiento, exhibición o análisis de artículos. No hay fuente autorizada
para activación con cuerpo completo según la documentación disponible. Antes
de un piloto deben quedar acreditadas condiciones de uso por fuente y la
aprobación operativa correspondiente. Las fuentes y el worker permanecen
deshabilitados.

## Validación de esta implementación

Las pruebas de PostgreSQL/PostGIS temporal comprueban creación atómica del
outbox, ausencia de duplicados, detección sólo de pares directos de la misma
fuente, exclusión de publicaciones en grupos vigentes, no reconciliación de la
cola histórica, reintentos y revisión manual, límite de comparables,
concurrencia `SKIP LOCKED`, y consumo desde el ciclo del worker sin fuentes
programadas. Las pruebas no consultan medios ni invocan Gemini.
