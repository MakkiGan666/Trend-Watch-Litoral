# Fase 1.2: ingesta y cobertura

## Alcance y hallazgos

Base local: `dace336899c05d41459b0275eb61b8d37f4e717c`, rama
`fix/stabilizacion-pr23-fase1-1`. La comparación local con PR #24
(`7acc16a7d0ef8fd5d10abe7be9a1594d48936981`) no muestra diferencias
para `app/core/services/scraper.py`.

Defectos confirmados por inspección y pruebas con mocks:

- Un sitemap fallido se omitía y la ejecución anunciaba EXITO, incluso sin candidatos.
- El truncamiento por límite no indicaba cobertura incompleta.
- Cero altas no distinguía período vacío de duplicados.
- RSS permitía títulos y contenidos vacíos. XML ajeno a RSS parecía un feed vacío.
- `zip` descartaba candidatos silenciosamente si la clasificación devolvía menos resultados.
- Las descargas urllib/newspaper no controlaban destinos DNS ni redirecciones.
- El scraper alternativo tampoco validaba destino ni campos mínimos.

Ya resueltos en la base y conservados: identidad SHA-256 del enlace recortado,
no actualización de históricos, deduplicación y colisiones concurrentes por hash,
savepoint por publicación, tratamiento de DataError y categorías desconocidas.
No se alteraron datos existentes, esquema, migraciones ni AUTH_USER_MODEL.

## Contrato

Se mantienen `status=EXITO/ERROR` y los contadores existentes. Se agregan
`estado`, `cobertura_completa` y `disponibles`. En resultados con registro se
conservan registro_id, errores y categorías, incluso ante excepciones.
Los argumentos inválidos o el fallo al iniciar auditoría no generan registro.

| estado | status | Interpretación |
| --- | --- | --- |
| EXITO | EXITO | Universo descubierto cubierto, sin errores; hubo altas |
| SIN_RESULTADOS | EXITO | Cobertura completa, cero candidatos descubiertos |
| DUPLICADOS | EXITO | Cobertura completa, candidatos existentes, cero altas |
| PARCIAL | ERROR | Cobertura incompleta, con altas, duplicados o una fuente procesada |
| FALLO | ERROR | Operación no completada sin ese trabajo útil |

Procesar una fuente completa, aunque no tenga noticias, es trabajo útil: si otro
sitemap falla se informa PARCIAL, nunca SIN_RESULTADOS. Si todos fallan, FALLO.
`disponibles` cuenta entradas RSS antes del límite o URLs históricas únicas en el
período descubiertas; ante fallos de sitemaps es un mínimo conocido, no un total.
`omitidas` sigue contando duplicados; no cuenta descartes por errores ni límites.

Cobertura significa el universo anunciado por el feed/sitemaps consultados, no
una garantía de que el editor publique todas sus noticias en esos documentos.
Los límites dejan cobertura incompleta cuando quedan candidatos sin atender.
No se intentan descargar nuevamente los duplicados ni se cambia su contenido.

Un resumen RSS no vacío puede conservarse si falla la extracción del cuerpo,
pero se registra `extraccion_incompleta` y el resultado es parcial. Nunca se
guardan publicaciones normales sin título, contenido o URL válida; la URL y su
hash mantienen la identidad histórica. Fecha, imagen y departamento siguen siendo
opcionales. No se impone longitud mínima arbitraria al título o al contenido.

`RegistroDatos.estado` conserva EXITO para coberturas completas y usa
`ERROR: PARCIAL/FALLO` para cierres incompletos. Una excepción guarda el prefijo
ERROR y detalle acotado. No se requiere migración.

## Consumidores

API (`views.py`), ejecución programada (`gemini_cliente.py`), comandos
`ejecutar_scraper`, `ingestar_historico` y `run_pipeline` ya exigen status EXITO:
los parciales ahora siguen sus rutas de error existentes y no anuncian éxito ni
continúan automáticamente hacia IA. Las publicaciones guardadas se conservan.
No hay nuevos valores en status ni cambio de estructura pública obligatorio.
Cambió deliberadamente el criterio de éxito: errores individuales, fallback RSS
y límites pendientes ya no son EXITO. Los códigos HTTP y códigos de salida de
las rutas de error existentes se mantienen; PARCIAL no dispone de una nueva
presentación específica en frontend, fuera del alcance de esta fase.

El scraper alternativo conserva su retorno de lista, PK externa y propagación de
excepciones. Usa el mismo transporte, rechaza categorías desconocidas y entradas
incompletas antes de guardar el lote. La unificación de su identidad con el
servicio oficial queda fuera del alcance para no reinterpretar históricos.

## Red y límites residuales

El transporte acepta solamente HTTPS/443, sin credenciales, para los dos hosts
exactos de El Territorio. Rechaza controles, barras inversas, fragmentos y puertos
inválidos. Cada salto se valida antes de resolver; se rechazan resoluciones
vacías, privadas, loopback, link-local, multicast, reservadas y transiciones IPv6.
Una respuesta DNS mixta también se rechaza. Se conecta al sockaddr validado sin
segunda resolución; TLS verifica certificado y hostname original. No se usan
proxies del entorno. Se limita el cuerpo a 8 MiB y las redirecciones a seis
respuestas (cinco saltos seguidos de respuesta final).

Newspaper recibe HTML ya descargado y `fetch_images=False`, evitando su descarga
autónoma del artículo y de imágenes. No se descarga ninguna imagen en estos
servicios; los enlaces opcionales de imagen conservan su validación anterior.

No se verificó el comportamiento de la versión instalada de newspaper mediante
integración: no hay Django/newspaper disponibles en el Python del anfitrión.
Las pruebas comprueban el uso de input_html y fetch_images con mocks. Antes de
liberar debe verificarse en el entorno descartable que esa dependencia respeta
ambas opciones, manteniendo bloqueo de red como defensa de prueba.

La política excluye HTTP y hosts CDN diferentes; si el editor cambia destinos se
informará error, sin ampliar automáticamente la lista. No hay prueba de
conectividad al medio, por restricción expresa. El transporte confía en TLS, el
resolver y el enrutamiento del sistema; no sustituye una política de egreso.
No se impone un plazo global al resolver DNS ni un máximo de sitemaps/candidatos;
esos límites operativos y reintentos quedan pendientes.

## Validación

`python3 tools/fase1_2/test_unit.py`: pruebas de biblioteca estándar, transporte
real con sockets/DNS simulados y servicio real con Django/ORM simulados. No
acceden a bases ni red. Este arnés no demuestra transacciones, constraints,
concurrencia ni compatibilidad de dependencias reales.

Se agregaron seis regresiones con ORM real a `core.test_ingesta_historico` y se
adaptaron sus mocks y expectativas de parcialidad. Las pruebas del scraper
alternativo en `core.tests` simulan ahora la nueva frontera HTTP.

Django check, suite Django y suite PostgreSQL NO se ejecutaron: el intérprete
local informa `ModuleNotFoundError: No module named 'django'`. No se instalaron
dependencias ni se invocó Docker, Compose o el arnés PostgreSQL. Las 64 pruebas
PostgreSQL de Fase 1.1 no validan estos cambios.

Siguiente paquete: ejecutar en un entorno descartable ya equipado la suite de
ingesta (incluyendo las tres pruebas PostgreSQL), consumidores API/pipeline y
check; agregar una integración de newspaper con HTML local y sockets bloqueados.
Después, abordar límites globales de recursos y una presentación de parciales
sin cambiar unilateralmente los contratos públicos.

Fase 1.1: `docker-compose.yml` y `tools/fase1_1/` se preservan sin modificaciones
adicionales. No se hicieron operaciones de historia Git ni se usaron credenciales.

Resultado final de esta sesión: **26 pruebas sin dependencias, 26 exitosas**
(`Ran 26 tests in 0.221s`, `OK`). `compileall` de los seis archivos Python
modificados/nuevos finalizó con código 0; `git diff --check`, código 0.
La comprobación de rutas Git confirmó que todos los archivos modificados y no
rastreados están dentro del worktree. Se comprobó por contenido que Compose
coincide exactamente con el cambio inicial de Fase 1.1. HEAD permanece en la base.
