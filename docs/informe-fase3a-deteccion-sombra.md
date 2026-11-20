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
