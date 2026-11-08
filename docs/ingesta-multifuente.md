# H4.1 — Ingesta multifuente explícita

El servicio `core.services.orquestador_multifuente.ejecutar_ingesta_multifuente`
integra catálogo, transporte HTTPS, lector RSS, extracción HTML, persistencia y
cola IA. El comando `ingestar_multifuente` ejecuta una sola revisión; no agenda
ciclos, aplica migraciones ni altera el catálogo o los comandos de El Territorio.

## Selección y configuración

Las 18 fuentes siguen deshabilitadas. El comando exige al menos un `--fuente` y
rechaza IDs desconocidos o deshabilitados antes de descargar. Habilitar fuentes
requiere una revisión separada del catálogo; no existe opción de activación.

Con fuentes habilitadas por una revisión independiente, ejemplos de uso:

```bash
python app/manage.py ingestar_multifuente --fuente misiones_online --dry-run --sin-ia
python app/manage.py ingestar_multifuente --fuente misiones_online --fuente primera_edicion --limite-fuente 3 --limite-total 6 --sin-ia
python app/manage.py ingestar_multifuente --fuente misiones_online --con-ia --limite-ia 2
```

Con el catálogo actual, esos ejemplos terminan con un error de fuente deshabilitada.
Antes de cualquier descarga o escritura, también en dry-run, el preflight verifica
las tablas y columnas del circuito, sus tipos, longitudes y nulabilidad conforme
a los modelos, la unicidad y FK de alias de `0020`, la PK/FK
de la cola de `0021` y la unicidad de `hash_origen`. Si falta algo, termina con
un error explícito de esquema y sin registros de ejecución. No consulta un plan
para aplicarlo ni crea tablas o ejecuta migraciones.

| Opción | Predeterminado | Máximo |
| --- | ---: | ---: |
| `--limite-fuente` | 3 | 30 y el límite canónico de cada fuente |
| `--limite-total` | 10 | 100 |
| `--limite-ia` | 5 | 20 llamadas por ejecución |

Los límites cuentan entradas RSS admitidas para trabajar, incluidas repeticiones
y noticias ya conocidas. Una consulta canónica adicional consume otra unidad,
salvo que esa URL ya esté presupuestada como otra entrada del mismo lote o esté
en caché. Se respetan tanto el cupo de la fuente como el global. Al agotar el total
no se descargan los feeds
restantes. El lector conserva sus límites canónicos de entradas y bytes; nunca
se modifica una `FuenteRSS` para aumentar permisos. Cada petición y redirect sigue
H2.1: DNS/IP públicos, TLS y hosts de la misma fuente, sin proxies ni imágenes.

## IA, dry-run y deduplicación

Gemini está desactivado por defecto. `--sin-ia` lo declara explícitamente;
`--con-ia` lo habilita sólo para los IDs del resultado de esta ejecución, con el
límite global indicado y la pausa de 12 segundos entre llamadas, también entre
fuentes. No consume pendientes de otras ejecuciones ajenas al lote.
H3.1 crea su cola durable aunque se use `--sin-ia`. Las reservas y los envíos
inciertos conservan las protecciones de H3.2 y no se reenvían automáticamente.

`--dry-run` permite descargas seguras y consultas de identidad, pero no crea
publicaciones, registros, alias ni trabajos IA, y nunca llama a Gemini, incluso
combinado con `--con-ia`.

La caché dura una ejecución y utiliza fuente + URL normalizada; conserva también
fallos para evitar repetir peticiones. Se omite HTML si la URL ya tiene un alias
persistido y H3.1 confirma una identidad sin conflictos. Los históricos sin alias
se extraen para aprender la canónica mediante H3.1, preservando sus hashes e IDs.
La normalización sólo elimina tracking conocido y conserva parámetros funcionales.
La caché comparte y reutiliza extracciones sólo después de validarlas con H3.1,
sin guardar ni invocar IA: contenido suficiente, campos válidos y ausencia de
caracteres de control, entre otras comprobaciones. Las extracciones inválidas
no se comparten como resultados válidos de una canónica. Si declaran otra canónica autorizada, se intenta recuperarla con H2.1
y el presupuesto disponible. Un conjunto de URLs visitadas corta los ciclos;
la caché de respuestas evita volver a descargar la misma URL, incluso al fallar.

## Resultado

Stdout contiene un único JSON; los mensajes heredados se envían a stderr. Incluye
los totales y el detalle por fuente:

- `descargadas`: respuestas completas de transporte, RSS + HTML, sin contar
  redirects intermedios; se desglosa en `feeds_descargados` y `articulos_descargados`.
- `entradas_rss_validas`: noticias que normalizó H2.2 dentro de su límite canónico,
  antes del límite menor del orquestador (detalle por fuente).
- `validas`: entradas reconocidas por identidad o aceptadas por H3.1.
- `rechazadas`: rechazos del lector, extracción y persistencia. Una caída inesperada
  de persistencia se informa como `persistencia_incierta`, sin afirmar que todas
  sus noticias hayan sido rechazadas ni deshacer commits ya confirmados.
- `nuevas`, `duplicadas`: altas reales e identidades ya existentes; `previstas`
  separa las altas potenciales del dry-run.
- `pendientes_ia`: trabajos todavía enviables de los IDs de este lote;
  `pendientes_ia_previstas` indica los trabajos potenciales del dry-run.
- `errores`: etapa, fuente, índice y código, sin cuerpos de noticias ni credenciales.
- `limitada`: quedaron fuentes, entradas o consultas canónicas adicionales fuera
  del presupuesto solicitado.

`EXITO` indica ausencia de errores dentro del alcance solicitado; revisar siempre
`limitada`. `PARCIAL` conserva datos de fuentes leídas aunque haya errores.
`FALLO` indica que ninguna fuente pudo leerse correctamente; el comando emite el
JSON y termina con error. Errores de selección o parámetros terminan antes de
iniciar la ejecución. Un preflight de esquema fallido también termina con error,
sin emitir un resumen `EXITO`/`PARCIAL` ni descargar fuentes.

Las pruebas usan fixtures locales, conexiones HTTP simuladas, Gemini simulado sólo
con opt-in explícito y bases efímeras. No validan cambios recientes de los sitios
reales ni habilitan fuentes de producción.
