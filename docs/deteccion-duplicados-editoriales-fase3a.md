# Fase 3A: detección editorial en modo sombra

## Alcance y garantías

La fase agrega una cola persistente para observaciones del detector existente.
No se invoca desde el arranque de Django, las vistas, el buscador ni el pipeline
de ingesta. Sólo se ejecuta desde el comando de auditoría con
`--registrar-sombra`. No crea `GrupoEditorial`, membresías ni eventos de revisión;
tampoco cambia, oculta o elimina publicaciones.

`--dry-run` continúa siendo estrictamente de lectura. El modo de escritura añade
filas únicamente a `core_candidato_duplicado_editorial`. Cada par se vuelve a
leer y evaluar desde `Publicacion`; los resultados y textos suministrados por el
llamador no se aceptan como evidencia. El límite es de 5.000 pares por llamada.

## Clasificación

- **EXACTO**: misma fuente normalizada y misma URL canonicalizada. Significa
  identidad exacta de URL según la canonicalización local, no igualdad literal
  del contenido editorial.
- **PROBABLE**: el detector considera confirmada la identidad por título,
  fecha y similitud alta del cuerpo, o la clasifica como probable. Requiere
  revisión humana antes de cualquier agrupación.
- **AMBIGUO**: hay datos incompletos (incluidas fichas RSS sin cuerpo) o una
  coincidencia nominal sin evidencia independiente suficiente.

Los estados `COBERTURA_MULTIMEDIO`, `TITULO_COINCIDENTE_ENTRE_FUENTES` y
`TITULO_COINCIDENTE_DISTINTO_CONTENIDO` no se persisten como candidatos a
duplicado. En particular, medios distintos nunca se agrupan sólo porque cubren
el mismo acontecimiento. Una publicación con membresía vigente de un grupo
editorial se omite para no interferir con las decisiones existentes.

## Idempotencia, evidencia y transitividad

La clave idempotente es SHA-256 de `version_detector:publicacion_a:publicacion_b`,
con los IDs ordenados numéricamente. La restricción única de base de datos es la
última defensa ante ejecuciones concurrentes. Una repetición actualiza la última
observación, el contador y la evidencia vigente de esa misma versión; conserva
la primera fecha observada. Una versión nueva del detector obtiene una clave
distinta y mantiene visible el historial de versiones.

La evidencia conserva estado y explicación del detector, similitudes,
diferencia de fechas, igualdad de URL, hashes de URLs canonicalizadas y huellas
SHA-256 de los campos editoriales. No guarda cuerpos completos. La evidencia
serializada está limitada a 8 KiB. Cada comparación es un par directo: el
sistema no construye componentes conexas, grupos ni inferencias transitivas.

## Ejecución y revisión

```sh
python manage.py auditar_duplicados_editoriales --dry-run --fuente "El Territorio" --titulo-minimo 35
python manage.py auditar_duplicados_editoriales --registrar-sombra --fuente "El Territorio" --titulo-minimo 35
```

El primer comando no escribe. El segundo persiste sólo la cola; informa el
conteo actualizado y deja explícito que creó cero grupos y modificó cero
publicaciones. Se recomienda limitar fuente y alcance al ejecutar el comando.
La cola se consulta en Django Admin por usuarios con
`core.revisar_candidatos_editoriales`; la interfaz no permite añadir, editar,
borrar ni activar candidatos. Toda agrupación futura debe seguir el flujo de
revisión individual de los servicios editoriales existentes.

## Compatibilidad y referencia histórica

La referencia de fase 2C informa 79 grupos de alta evidencia y 81 aristas
directas (78 pares y un grupo de tres miembros comparado como tres pares). La
prueba automatizada reproduce esa estructura con IDs, fechas, titulares y URLs
sintéticos; no importa los datos de producción ni prueba automáticamente esos
79 grupos históricos. Los cuatro grupos ya aprobados no se leen ni modifican
durante pruebas aisladas; en cada ejecución real el servicio omite cualquier
publicación con membresía vigente.

## Pruebas y operación

Las pruebas focalizadas comprueban clasificación exacta/probable/ambigua,
falsos positivos, separación entre medios, referencia de 79 grupos/81 pares,
integridad de la cola, idempotencia, revalidación desde la base, omisión de
membresías vigentes y concurrencia. Las pruebas se ejecutan sólo en PostgreSQL
temporal (39 pruebas focalizadas aprobadas). Esta fase no activa detección periódica; la integración con el
planificador de ingesta o con decisiones editoriales requiere una fase posterior
y aprobación explícita.
