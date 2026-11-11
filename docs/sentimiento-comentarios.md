# Análisis automático de sentimiento sobre comentarios

Esta funcionalidad agrega una capa de análisis sobre los comentarios que los
usuarios dejan en una publicación. Es independiente del sentimiento del
contenido de las noticias (modelo `Sentimiento`) y de la valoración manual del
lector (`ValoracionPublicacion`). Las tres fuentes nunca se combinan en un
único indicador: cada registro aclara su método, modelo y fecha de análisis
para no presentar la predicción como una verdad objetiva.

## Modelo

`core.SentimientoComentario` (migración `0011_sentimientocomentario`):

| Campo                | Descripción                                                        |
|----------------------|--------------------------------------------------------------------|
| `comentario`         | `OneToOneField` con `on_delete=CASCADE`. Una fila por comentario.  |
| `polaridad`          | Float en `[-1, 1]`. `NULL` si el estado es `error`.                |
| `confianza`          | Float en `[0, 1]`. `NULL` si el estado es `error`.                 |
| `metodo`             | `lexicon` o `ia`.                                                  |
| `modelo`             | Identificador versionado (`lexicon_v2`, `ollama:llama3.1:latest`). |
| `texto_hash`         | SHA-256 del texto analizado; cambia si el comentario se edita.     |
| `categoria`          | FK nullable a `Categoria` (migración `0012`): una de las 12 categorías del proyecto, la misma tabla que usan las noticias. `NULL` si no se pudo determinar o en error. |
| `estado`             | `procesado` o `error`.                                             |
| `codigo_error`       | En `error`, el fallo (p. ej. `excepcion_inesperada`). En un resultado `procesado` con `metodo=lexicon`, `ia:<código>` indica que se pidió IA y falló (p. ej. `ia:ollama_sin_respuesta`). |
| `fecha_analisis`     | Fecha del primer análisis.                                         |
| `fecha_actualizacion`| Fecha del último registro.                                         |

Restricciones en la base: polaridad y confianza dentro de rango, y la combinación
`estado=procesado` exige valores numéricos (no se guarda un procesado sin predicción).

Reanalizar un comentario actualiza la misma fila: no se guarda historial de
versiones, pero sí quedan la fecha original (`fecha_analisis`) y la última
(`fecha_actualizacion`). La próxima etapa podrá incorporar historial si surge
la necesidad.

## Servicio

`core/services/sentimiento_comentarios.py` expone:

- `predecir_lexicon(texto)`: usa `analyze_sentiment_lexicon` y
  `compute_probabilistic_sentiment` existentes. Determinista, sin red. La
  categoría sale de las reglas de las noticias (`categoria_con_confianza`) y
  sólo se asigna si son seguras; si no, queda `NULL` (no se usa la categoría
  por defecto).
- `predecir_ollama(texto)`: pide a Ollama (`/api/generate`, `format=json`) un
  JSON con `polaridad`, `confianza` y `categoria`. El prompt enumera las 12
  categorías de `CATEGORIAS_PROYECTO`. Reglas de la categoría:
  - una categoría de la lista se conserva (se aceptan diferencias de
    mayúsculas y tildes);
  - `null` o ausencia se admiten y quedan sin categoría (`NULL`);
  - una categoría fuera de la lista (p. ej. "Transporte") o que no sea texto se
    descarta y queda `NULL`: la polaridad y la confianza se conservan si son
    válidas, el resultado sigue siendo `metodo='ia'` y se registra un aviso en
    el log. No se crean categorías nuevas ni se buscan equivalencias.

  La polaridad (número en [-1, 1]) y la confianza (número en [0, 1]) siguen
  siendo obligatorias: si faltan, no son numéricas o están fuera de rango, la
  respuesta se rechaza aunque la categoría sea válida. Si falla por red,
  timeout o formato (JSON inválido), lanza `SentimientoNoDisponible`.
- `analizar_comentario(comentario, usar_ia=False, forzar=False)`: orquesta la
  predicción, persiste y responde `('creado' | 'actualizado' | 'omitido')`.
  Si `usar_ia=True` falla, cae automáticamente al método léxico, lo registra
  como `metodo='lexicon'` para que la UI no afirme algo falso y guarda
  `codigo_error='ia:<código>'`. Un resultado así se reintenta con IA la
  próxima vez que se pida IA, aunque el texto no haya cambiado.
- Si la categoría elegida todavía no existe en la tabla `Categorias` (por
  ejemplo "Tecnología" antes de ingerir una noticia de esa categoría), se crea
  igual que en la ingesta de noticias. Nunca se crean nombres fuera de la lista.
- `calcular_texto_hash(texto)`: SHA-256 del texto normalizado (strip).
- `sentimiento_vigente(comentario)`: única definición de vigencia (estado
  `procesado` y hash igual al texto actual). La usan el análisis, el registro
  de errores y `contexto_comentarios`; el modelo `Comentario` no se modifica.
- `candidatos_sin_analisis_validos()` y `candidatos_con_hash_desactualizado()`:
  iteradores para procesamiento por lote.

El servicio nunca se invoca dentro del flujo HTTP de creación o edición de
comentarios: el usuario publica el comentario sin esperar al análisis.

## Análisis automático en segundo plano

`core/services/analisis_automatico.py`. Al publicar o editar un comentario,
la vista registra `programar_analisis(pk)` con `transaction.on_commit`: recién
después del commit se encola el id y la respuesta vuelve enseguida.

- Un único hilo trabajador por proceso (daemon) consume la cola y analiza de
  a un comentario, así las llamadas a Ollama no se superponen.
- Un comentario no se encola dos veces mientras espera. El trabajador relee
  el comentario de la base: una edición posterior se analiza con el texto
  actual y un reproceso sin cambios se omite por hash.
- Cualquier excepción queda en el log; si no hay un análisis vigente se
  registra `estado='error'`. Un error al encolar nunca afecta la publicación.
- La cola vive en memoria: si el servidor se reinicia antes de procesar, el
  comentario queda pendiente y lo recupera el comando de respaldo.
- La interfaz muestra "Análisis automático pendiente" mientras no hay
  resultado vigente; la insignia aparece al recargar.

Variables de entorno (opcionales):

- `SENTIMIENTO_COMENTARIOS_AUTOMATICO`: `0` lo desactiva (por defecto activo).
- `SENTIMIENTO_COMENTARIOS_METODO`: `ia` (por defecto) o `lexicon`.

Con varios procesos (por ejemplo gunicorn con dos workers) cada proceso tiene
su propia cola y su propio hilo.

## Comando de management (respaldo)

```
python app/manage.py analizar_sentimiento_comentarios [--limite N] [--reanalizar] [--metodo lexicon|ia] [--dry-run]
```

- Es **idempotente**: no toca los comentarios cuyo texto no cambió desde el
  último análisis (comparación por `texto_hash`).
- `--reanalizar` fuerza el reproceso de todos (útil al cambiar la versión o
  el método). Recorre cada comentario una sola vez por corrida, incluidos
  nuevos, errores y editados; `--limite` cuenta comentarios únicos.
- `--metodo ia` intenta usar Ollama; si falla, cae al léxico sin interrumpir
  el lote. Además incluye los comentarios que quedaron con léxico porque la IA
  había fallado (`codigo_error='ia:...'`), para recuperarlos cuando Ollama
  vuelve a estar disponible. Cada comentario se procesa una sola vez por corrida.
- Los análisis anteriores a la migración `0012` no tienen categoría; para
  completarla, correr `--reanalizar`.
- `--dry-run` imprime qué se procesaría sin escribir en la base.
- Un error inesperado por comentario queda registrado con `estado='error'` y
  un `codigo_error`; el lote continúa. Si el comentario ya tenía un análisis
  vigente (por ejemplo, con `--reanalizar`), ese análisis se conserva sin
  cambios y el comando lo informa por stderr. Si el análisis previo estaba
  desactualizado, se registra el error porque no hay resultado vigente.

### Reintento de errores

Un comentario con `estado='error'` vuelve a ser candidato en la próxima
corrida (lo cubren `candidatos_sin_analisis_validos()`). No hay backoff
automático: si el servicio externo sigue caído, el error se reemplaza por
otro error y el comentario vuelve a quedar en la lista.

## Configuración de Ollama

El servicio lee las variables de entorno siguientes. Todas son opcionales y
usan valores por defecto compatibles con un Ollama local:

- `OLLAMA_BASE_URL` (default `http://127.0.0.1:11434`)
- `OLLAMA_MODELO_CHAT` (default `llama3.1:latest`)
- `OLLAMA_TIMEOUT` segundos (default `20`)

Si `httpx` no está instalado, el método `ia` queda deshabilitado y las
corridas caen al método léxico. Agregar la dependencia a
`requirements.txt` cuando se decida habilitar Ollama en despliegues reales.

## Interfaz

En `partials/_sentimiento_comentario.html` se renderiza un badge discreto bajo
cada comentario cuando hay un análisis en estado `procesado`. El badge:

- Nunca modifica ni oculta el texto del comentario.
- Indica el método y el modelo utilizados en el `title` del elemento.
- Muestra la confianza con dos decimales.
- Aclara explícitamente que la etiqueta es una "predicción automática".
- No aparece si el análisis todavía no se ejecutó o si está en error, para no
  presentar un dato que no existe.
- Sólo aparece si el hash del análisis coincide con el texto actual. Después
  de editar, el resultado anterior se conserva pero se oculta hasta que el
  comando lo actualice; no se llama a Ollama durante la edición HTTP.

Las respuestas de Ollama deben tener un objeto JSON exterior con `response`
de tipo texto, que contenga el JSON de la predicción. Envoltorios inválidos,
errores HTTP, timeouts, `OLLAMA_BASE_URL` mal formada (`httpx.InvalidURL`),
JSON anidado en exceso (`RecursionError`), enteros que no caben en un float
(`OverflowError`) y predicciones inválidas activan el fallback léxico.

## Separación respecto de otras fuentes

| Fuente                     | Modelo                   | Significado                                       |
|----------------------------|--------------------------|---------------------------------------------------|
| Sentimiento de noticia     | `Sentimiento`            | Polaridad calculada sobre el texto de la noticia. |
| Voto manual del lector     | `ValoracionPublicacion`  | Elección explícita de la persona (positivo/neutral/negativo). |
| Sentimiento de comentario  | `SentimientoComentario`  | Predicción automática sobre el texto del comentario. |

Las tres se almacenan en tablas distintas y no deben agregarse en un único
promedio. Toda métrica agregada debe nombrar su fuente y su denominador.

## Pruebas

```
python app/manage.py test core.test_sentimiento_comentarios
```

Las pruebas no requieren Ollama corriendo: la integración con el servidor
externo se mockea con `unittest.mock`.
