# Seguimiento de IA y etiquetas temáticas

## Seguimiento de IA (`EjecucionIA`)

Cada llamada a un modelo queda registrada una vez, desde `core/services/ia/seguimiento.py`:

| Operación | Dónde se registra | Entidad |
|---|---|---|
| Sentimiento y localidades de noticias | `GestorIA` + `gemini_cliente.procesar_pendientes` | publicación |
| Clasificación de categorías (ingesta) | `GestorIA` + `clasificacion._clasificar_con_ia` | lote |
| Extracción territorial (departamentos) | `GestorIA` + `clasificacion_departamentos.consultar_ia` | lote (ids en `referencias`) |
| Etiquetas temáticas | `GestorIA` + `etiquetas_ia.etiquetar_publicacion` | publicación |
| Sentimiento de comentarios (Ollama) | `sentimiento_comentarios.predecir_ollama` | comentario (sin copiar el texto) |

- Una fila por intento de proveedor: si Gemini falla y responde Ollama como respaldo, hay dos filas (`respaldo=True` en la segunda).
- `respuesta_original` nunca se modifica. El servicio completa `resultado` (lo que usa el sistema) o marca el registro como `invalida`.
- Estados: `exitosa`, `fallida` (el modelo no respondió) e `invalida` (respondió, pero no superó la validación).
- No se guardan claves: además de no enviarlas, se reemplaza cualquier aparición de `GEMINI_API_KEY`/`GOOGLE_API_KEY`.
- Un error al guardar el historial se registra en el log y se ignora: nunca interrumpe el análisis.
- El historial no se borra con la publicación (sin restricción de clave foránea).
- La prueba de conexión y de generación del panel «Motor de IA» no se registra: es una comprobación de salud y no guarda datos.

Panel: **Administradores → Seguimiento de IA** (`/administradores/seguimiento-ia/`). Tiene el mismo acceso que «Motor de IA»: sólo el rol Administrador o los superusuarios. Permite filtrar por tipo de análisis, proveedor, modelo, estado, fecha y publicación, y abrir cada ejecución.

## Etiquetas temáticas con IA

Las publicaciones conservan su categoría principal (`Tema` → `Categoria`). Las etiquetas comparten el catálogo `Etiqueta`; `PublicacionEtiqueta.origen` distingue:

- `lexico`: extracción del texto sin IA (ver `etiquetas-noticias.md`), que se recalcula al editar la noticia.
- `ia`: etiquetas validadas a partir de una respuesta de IA, con `ejecucion`, `modelo_ia` y `fecha_asignacion`.

Cada origen se sincroniza por separado: editar el texto recalcula sólo las léxicas.

Validación de cada etiqueta propuesta por el modelo:

1. Normalización del nombre.
2. Largo de 3 a 60 caracteres y hasta 5 palabras.
3. No genérica.
4. No repite la categoría principal.
5. Sin duplicados (incluido singular y plural).
6. Respaldo en el texto: cada palabra significativa tiene que aparecer en la noticia.

El historial guarda las etiquetas descartadas con su motivo. Una respuesta fallida o inválida no borra las etiquetas vigentes. Si existe una etiqueta equivalente en el catálogo (también en singular o plural), se reutiliza.

### Ejecución (siempre manual)

No corre durante la ingesta ni al guardar. Sin `--confirmar` sólo muestra qué haría, sin llamar al modelo:

```text
python manage.py etiquetar_con_ia --ids 120 121 122              # vista previa
python manage.py etiquetar_con_ia --ids 120 121 122 --confirmar
python manage.py etiquetar_con_ia --limite 5 --confirmar          # 5 recientes sin etiquetas de IA
```

- Máximo 25 publicaciones por ejecución, con una pausa de 4 s entre llamadas (`--pausa`).
- Las ya etiquetadas se omiten, salvo con `--rehacer`.
- Usa el motor principal y el respaldo configurados en «Motor de IA».

## Consultas temáticas (`core/services/temas.py`)

| Función | Qué hace |
|---|---|
| `filtrar_por_etiquetas` | Filtra por varias etiquetas (todas deben estar). |
| `etiquetas_coocurrentes` | Etiquetas que aparecen junto a las elegidas. |
| `frecuencia_etiquetas` | Etiquetas más frecuentes. |
| `etiquetas_en_alza` | Compara con el período anterior de igual duración; sin base de comparación no inventa un porcentaje. |
| `etiquetas_por_departamento` y `departamentos_de_etiqueta` | Relación con el territorio; sólo usan `Publicacion.departamento` identificado. |
| `sentimiento_por_etiqueta` | Tono por etiqueta; sólo cuenta análisis válidos. |
| `evolucion_etiqueta` | Serie semanal de una etiqueta. |
| `publicaciones_relacionadas` | Noticias con etiquetas en común, ponderadas por rareza. |

Uso en la interfaz:

- **Página de una etiqueta:** combinación de etiquetas (`/etiquetas/<slug>/?y=<otra>`) y departamentos donde se concentra.
- **Detalle de la noticia:** temas de IA, palabras clave, departamento y noticias relacionadas.
- **Dashboard** (sección Temática): frecuentes, en alza, por departamento y tono negativo. Usa las etiquetas de IA cuando existen y, si no, las palabras clave, indicando siempre el origen.
