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
| `modelo`             | Identificador versionado (`lexicon_v1`, `ollama:llama3.1:latest`). |
| `texto_hash`         | SHA-256 del texto analizado; cambia si el comentario se edita.     |
| `estado`             | `procesado` o `error`.                                             |
| `codigo_error`       | Código corto que explica un fallo, por ejemplo `ollama_sin_respuesta`. |
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
  `compute_probabilistic_sentiment` existentes. Determinista, sin red.
- `predecir_ollama(texto)`: pide a Ollama (`/api/generate`, `format=json`) un
  JSON con `polaridad` y `confianza`. Valida tipo, rango y claves. Si falla
  por red, timeout o formato, lanza `SentimientoNoDisponible`.
- `analizar_comentario(comentario, usar_ia=False, forzar=False)`: orquesta la
  predicción, persiste y responde `('creado' | 'actualizado' | 'omitido')`.
  Si `usar_ia=True` falla, cae automáticamente al método léxico y lo registra
  como `metodo='lexicon'` para que la UI no afirme algo falso.
- `calcular_texto_hash(texto)`: SHA-256 del texto normalizado (strip).
- `sentimiento_vigente(comentario)`: única definición de vigencia (estado
  `procesado` y hash igual al texto actual). La usan el análisis, el registro
  de errores y `contexto_comentarios`; el modelo `Comentario` no se modifica.
- `candidatos_sin_analisis_validos()` y `candidatos_con_hash_desactualizado()`:
  iteradores para procesamiento por lote.

El servicio nunca se invoca dentro del flujo HTTP de creación o edición de
comentarios: el usuario publica el comentario sin esperar al análisis.

## Comando de management

```
python app/manage.py analizar_sentimiento_comentarios [--limite N] [--reanalizar] [--metodo lexicon|ia] [--dry-run]
```

- Es **idempotente**: no toca los comentarios cuyo texto no cambió desde el
  último análisis (comparación por `texto_hash`).
- `--reanalizar` fuerza el reproceso de todos (útil al cambiar la versión o
  el método). Recorre cada comentario una sola vez por corrida, incluidos
  nuevos, errores y editados; `--limite` cuenta comentarios únicos.
- `--metodo ia` intenta usar Ollama; si falla, cae al léxico sin interrumpir
  el lote.
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
