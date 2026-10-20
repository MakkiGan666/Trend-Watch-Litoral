# Preparación de validación integral Fase 1.2

Fecha: 20/10/2026. Worktree:
`/home/sebas/Escritorio/trendwatch-pr23-estabilizacion`.
Rama: `fix/stabilizacion-pr23-fase1-1`.
HEAD: `dace336899c05d41459b0275eb61b8d37f4e717c`.

## Estado

Preparación revisada y comprobada sin Docker. No se ejecutaron Docker, Compose,
el arnés PostgreSQL, instalaciones, scraping, Gemini ni conexiones a bases.
Las 64 pruebas PostgreSQL de Fase 1.1 son el antecedente informado por el usuario;
no son resultados de esta tarea. Las 118 seleccionadas por el nuevo plan están
**pendientes de ejecución integral**, incluido `newspaper` real.

## Plan aditivo

`tools/fase1_1/validation.py` conserva las tres etiquetas originales, en el mismo
orden y en una invocación separada. Conteo AST: **64 métodos de prueba**.
Después de su aprobación ejecuta un segundo bloque, de **54 métodos**:

| Selección | Métodos |
| --- | ---: |
| core.test_ingesta_historico | 29 |
| core.tests.IngestaTestCase | 1 |
| core.tests.IngestaRSSTestCase | 2 |
| core.tests.ScraperAlternativoTestCase | 6 |
| core.tests.EjecutarScraperCommandTestCase | 3 |
| core.tests.RunPipelineCommandTestCase | 6 |
| core.tests.ConsumidoresResultadoIATestCase | 4 |
| core.test_ingesta_validacion | 3 |

El módulo histórico incluye las **seis regresiones ORM** nuevas y las **tres
pruebas PostgreSQL** de DataError real y concurrencia. No se duplican etiquetas
entre ambos bloques. El conteo de métodos no equivale a pruebas ejecutadas;
los subtests contienen escenarios adicionales.

El runner comprueba PostGIS y ejecuta Django `check` antes de los dos bloques.
Cada `call_command('test', ...)` crea, migra y destruye su base descartable;
no usa keepdb. Si falla check o el bloque original, no ejecuta el siguiente.

## Newspaper y consumidores

`app/core/test_ingesta_validacion.py` agrega tres pruebas Django:

- Dependencia `newspaper.Article` real, con HTML en bytes construido localmente.
  Invoca `_leer_articulo` con sólo `_descargar` simulado. Comprueba título y cuerpo
  extraídos, `fetch_images=False` y tipo real Article. El HTML contiene imágenes
  con URLs ficticias. Bloquea sockets/DNS, requests y urllib, y contabiliza los
  intentos aun si la biblioteca captura sus excepciones. No usa fallback ni skip:
  dependencia ausente, parseo fallido o intento de red hacen fallar la prueba.
- PARCIAL/FALLO detienen API y endpoint alternativo antes de IA, preservando el
  resumen detallado y el código HTTP existente.
- Los cinco estados de ingesta en pipeline: sólo EXITO, SIN_RESULTADOS y
  DUPLICADOS permiten continuar hacia una IA simulada.

El bloqueo Python del runner se activa antes de django.setup e incluye resolución
DNS. Sigue siendo defensa adicional: libpq funciona en C y atraviesa los controles
propios de identidad. La frontera de aislamiento de red sigue siendo Docker.

## Condiciones de aislamiento revisadas

No se cambiaron `security.py`, Compose, modelos, migraciones ni código funcional
de ingesta durante esta preparación. `run.py` sólo agrega la copia del plan Python
al staging existente. `runner.py` delega la selección y el bloqueo de red al plan,
conservando sus controles de entorno, parámetros libpq, señal por conexión,
identidad SQL y mantenimiento administrativo dentro de la base descartable.

Se mantienen:

- Daemon local fijo y cliente confiable; configuración Docker temporal y entorno
  cerrado. No sudo, elevación ni cambios de permisos.
- Imágenes ya locales, fijadas por ID tras inspección, `--pull=never`.
- Red nueva interna, bridge IPv4 isolated, sin miembros ajenos ni puertos publicados.
- Contenedores nuevos identificados por UUID, sin privilegios, raíz de sólo lectura.
- PostgreSQL PGDATA/sockets/tmp en tmpfs; medios/uploads de Django bajo `/tmp` del
  contenedor. Sin volúmenes persistentes ni adopción de recursos preexistentes.
- Copia temporal de código `.py`/`.html`, sin `.env`, SQLite, medios, uploads,
  ocultos ni symlinks. Un único bind de código de sólo lectura.
- Identidad PostgreSQL comprobada por token, IP, puerto, usuario, base y PGDATA,
  antes de habilitar escrituras. Sólo `tw_disposable`/`test_tw_disposable`.
- Limpieza restringida a IDs, nombres y etiquetas propios. Sin limpieza global.

Estos controles se verifican estáticamente y con fixtures/mocks. **No se
inspeccionaron el daemon ni las imágenes reales en esta tarea.** Las condiciones
runtime se vuelven a exigir al ejecutar: un rechazo debe abortar, sin relajar las
validaciones automáticamente. Sigue vigente la confianza requerida en procedencia
de imágenes, daemon y kernel. El timeout de pruebas continúa en diez minutos.

## Comprobaciones realizadas sin Docker

Desde la raíz del worktree:

```sh
python3 -B -m unittest discover -s tools/fase1_1 -p 'test_*.py'
python3 -B -O -m unittest discover -s tools/fase1_1 -p 'test_*.py'
python3 -B tools/fase1_2/test_unit.py
python3 -B tools/fase1_1/check_ports.py
python3 -B -O tools/fase1_1/check_ports.py
```

Resultados: **32/32**, **32/32 con -O**, **26/26**, **2/2** y **2/2**,
respectivamente. Las 32 incluyen siete nuevas de preparación y las 25 anteriores
del arnés de seguridad. Comprueban selección de pruebas, 64 originales,
seis regresiones y tres PostgreSQL, orden/fallo del plan, restauración de guardas,
staging sin datos sensibles y ubicación del plan bajo controles del runner.

Compilación estática de los cinco Python nuevos/modificados: satisfactoria,
sin cargar Django ni generar bytecode. `git diff --check`: satisfactorio.

## Ejecución preparada para terminal normal de Linux Mint

**No ejecutada en esta tarea.** Sin instalar dependencias ni descargar imágenes:

```sh
cd /home/sebas/Escritorio/trendwatch-pr23-estabilizacion
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 /usr/bin/python3 -B tools/fase1_1/run.py
```

El entorno vacío evita heredar SSH/Docker/proxies y credenciales. Los permisos
normales del usuario sobre el socket deben ser suficientes. Se exige Docker Engine
Linux 28+ con soporte isolated y las imágenes locales compatibles indicadas en el
README de Fase 1.1. Si falta algún requisito, detenerse y registrar el rechazo;
no usar sudo, descargar imágenes ni ampliar allowlists para forzar la ejecución.

Verificar en la salida: check satisfactorio, **64 pruebas del bloque original**,
**54 del bloque Fase 1.2**, sin skips inesperados (en particular las tres PostgreSQL
y newspaper), ambos bloques OK y salida final 0 con limpieza completada.
Una interrupción forzada puede requerir revisión manual de los recursos cuyo UUID
imprime el arnés; no ejecutar prune ni eliminar recursos ajenos.

## Alcance de los cambios de preparación

- `tools/fase1_1/run.py`: incluir validation.py en staging.
- `tools/fase1_1/runner.py`: ejecutar plan aditivo con bloqueo de red reforzado.
- `tools/fase1_1/validation.py`: selección y orden de checks/suites, guardas Python.
- `tools/fase1_1/test_validation.py`: siete pruebas sin dependencias.
- `app/core/test_ingesta_validacion.py`: newspaper local y consumidores de estados.
- README de Fase 1.1 y este documento: estado y ejecución preparada.

Se preservaron las correcciones funcionales de Fases 1.1/1.2, el arnés de seguridad
preexistente y todas las pruebas anteriores. Sin commits, pushes ni merges.
