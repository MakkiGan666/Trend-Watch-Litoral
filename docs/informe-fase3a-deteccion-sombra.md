# Informe de implementación — Fase 3A

**Fecha:** 2026-11-20

**Base main:** `8a05f50068591c2d974cf81924d15c7b3e8863af`

**Rama de trabajo:** `feat/fase3a-deteccion-sombra`
**Worktree:** `/home/sebas/Escritorio/TrendWatch/fase3a-deteccion-sombra`
**Commit de implementación:** `d3109fe1d8badf0d0006c87388bd2b83e9387cfe`
**PR:** [#68](https://github.com/MakkiGan666/Trend-Watch-Litoral/pull/68)

## Resultado

Se implementó una cola persistente en sombra sobre el detector editorial
existente. La invocación es manual y explícita. No hay integración con el
buscador, el dashboard, la ingesta ni el arranque de Django. Ninguna ejecución
de esta tarea leyó o escribió la PostgreSQL habitual.

El clasificador usa `EXACTO` exclusivamente para una URL canonicalizada
idéntica dentro de la misma fuente. Las coincidencias confirmadas por título,
fecha y cuerpo, pero con URL diferente, se guardan como `PROBABLE`; los datos
insuficientes y coincidencias nominales no confirmadas quedan `AMBIGUO`. Las
coincidencias entre fuentes y los títulos parecidos con cuerpos diferentes se
descartan como falsos positivos para la cola de duplicados.

La persistencia usa una clave SHA-256 única de par ordenado y versión del
detector, contadores atómicos y evidencia compacta limitada a 8 KiB. Incluye
hashes de las publicaciones y de las URLs, métricas y fechas editoriales; no
almacena cuerpos completos. El servicio vuelve a cargar y reevaluar los IDs
desde PostgreSQL antes de persistir. Omite publicaciones con membresías
editoriales vigentes y sólo registra pares directos; no forma grupos
transitivos.

## Archivos

- `app/core/models.py`: modelo `CandidatoDuplicadoEditorial`.
- `app/core/migrations/0030_candidatos_duplicados_editoriales_sombra.py`: tabla,
  claves foráneas protegidas, restricciones e índices aditivos.
- `app/core/services/deteccion_sombra_editorial.py`: revalidación, clasificación,
  huellas, evidencia e idempotencia concurrente.
- `app/core/management/commands/auditar_duplicados_editoriales.py`: mantiene
  `--dry-run` y agrega `--registrar-sombra` explícito.
- `app/core/admin.py`: consulta de cola sólo para revisores, sin altas,
  modificaciones, eliminaciones ni acciones.
- `app/core/test_deteccion_sombra_editorial.py`: regresiones de cola y detector.
- `docs/deteccion-duplicados-editoriales.md`: sintaxis actualizada del comando.
- `docs/deteccion-duplicados-editoriales-fase3a.md`: reglas y operación.

## Validación

Entorno: PostgreSQL/PostGIS temporal en contenedor `tw-fase3a-pg-20261120`,
red `none`, sin puertos publicados, montajes hacia el repositorio ni
credenciales del entorno habitual. Las bases de prueba de Django se eliminaron
al terminar cada suite; el contenedor temporal y su volumen anónimo permanecen
aislados y sin puerto publicado. El runner montó el código del worktree en sólo
lectura. Se aplicaron migraciones únicamente en bases de prueba efímeras.

- **39/39 pruebas** de cola, concurrencia, detector existente y agrupación
  editorial aprobaron.
- Django `check`: sin problemas.
- `makemigrations --check --dry-run`: sin cambios adicionales.
- `sqlmigrate core 0030...`: sólo `CREATE TABLE`, claves foráneas, check
  constraints e índices para la nueva cola; no altera tablas históricas.
- `git diff --check`: limpio.
- La prueba de administración confirmó lectura con el permiso existente y
  ausencia de altas, cambios y eliminaciones.

### Referencia de los 79 grupos

El informe persistente de fase 2C describe 79 grupos de alta evidencia como
81 comparaciones directas: 78 pares y un grupo de tres miembros. La prueba
reproduce esa estructura con 159 registros completamente sintéticos y obtuvo
81 aristas sin inferencia transitiva. Diez ejecuciones del detector sobre esa
muestra dieron **16,576 ms de mediana**, **21,786 ms de p95** y **21,786 ms de
máximo** en este entorno. Es una medición del detector puro; no representa
una ejecución de carga sobre las noticias actuales.

No se releyeron ni cargaron los 79 grupos históricos desde PostgreSQL habitual.
El resultado de fase 2C indica que las comparaciones directas originales siguen
siendo `DUPLICADO_CONFIRMADO`; esta fase valida el flujo y la cardinalidad
estructural, no revalida cada cuerpo histórico actual.

## Estado de datos y operación

- No se crearon grupos, membresías ni eventos de revisión en una base habitual.
- No se cambiaron publicaciones, relaciones, buscador ni configuración.
- No se ejecutaron recolectores ni solicitudes externas.
- No se activó IA.
- H4.8 permanece en el SHA conocido `6d28eccf8588735390b6a00da56a51f20b563b78`.
- La rama fue publicada mediante push normal y el PR #68 está abierto contra
  `main`; no se hizo merge.

## Próximo punto de control

La fase 3A quedó publicada para revisión. La fase 3B, integración con ingesta,
el buscador o aprobación editorial, no está iniciada y requiere autorización
separada.

## Revisión focalizada del PR #68

La revisión posterior identificó y corrigió estos puntos:

- La cola ahora conserva el historial y marca cada candidato como `PENDIENTE`,
  `OBSOLETO` o `EN_GRUPO`. Una reevaluación explícita vuelve a leer la evidencia
  desde las publicaciones actuales; los pares que ya no clasifican quedan
  obsoletos. Al activar una agrupación, sus candidatos se marcan `EN_GRUPO` en
  la misma transacción. Después de una revocación sólo vuelven a `PENDIENTE` si
  una nueva ejecución vuelve a confirmar la evidencia.
- La reevaluación y los servicios de revisión/aprobación/revocación bloquean
  primero las publicaciones en orden de ID. Una prueba concurrente verificó
  que reevaluar y activar a la vez no deja una observación pendiente para una
  publicación que terminó en un grupo vigente. Las ejecuciones simultáneas
  también vuelven a consultar y bloquear la fila de cola después de adquirir
  esos bloqueos; esa regresión fue detectada por la primera repetición de las
  pruebas y quedó corregida.
- La cola técnica ahora elimina sus observaciones derivadas al borrar una
  publicación (`CASCADE` del ORM). Las membresías, grupos e historial editorial
  conservan `PROTECT`, de modo que la cola no agrega un bloqueo de borrado por
  sí sola y tampoco debilita las protecciones editoriales.
- Se agregó una restricción única explícita sobre el par ordenado y la versión
  del detector, además de la clave SHA-256.

La migración `0031_estado_candidato_editorial` agrega dos campos y restricciones
en la tabla de candidatos y cambia la política ORM de sus dos referencias. Es
aditiva respecto de las publicaciones y agrupaciones; no se aplicó a PostgreSQL
habitual.

### Validación de los registros históricos actuales

Se releyeron los 159 IDs y las 81 aristas directas documentadas para los 79
grupos, mediante el contenedor web habitual con una sola transacción PostgreSQL
`READ ONLY`. Los 159 IDs existían, no faltó ninguna arista y las 81 comparaciones
volvieron a resultar `DUPLICADO_CONFIRMADO`. La consulta sólo leyó los campos
necesarios en memoria y emitió conteos; no ejecutó ni aplicó `0030`, no creó
candidatos, y no modificó publicaciones, agrupaciones ni auditoría.

### Pruebas de esta corrección

- **32/32 pruebas** de detección sombra y agrupación editorial aprobaron en
  PostgreSQL/PostGIS temporal. Incluyen evidencia obsoleta, transición a grupo
  vigente y revalidación tras revocación, concurrencia entre activación y
  reevaluación, actualización concurrente de una publicación, unicidad
  explícita y borrado de la observación derivada.
- Django `check`: correcto.
- `makemigrations --check --dry-run`: sin cambios de modelo pendientes.
- `sqlmigrate core 0031_estado_candidato_editorial`: sólo agrega campos y
  restricciones a la cola. No genera operaciones SQL para los cambios de
  `on_delete`, que se aplican en el recolector ORM.
- `git diff --check`: correcto.

No se modificó PostgreSQL habitual, Docker, H4.8, buscador, recolectores ni
agrupaciones activas. El PR #68 continúa sin fusionar.
