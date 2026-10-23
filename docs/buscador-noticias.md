# Buscador público de noticias

Backend de lectura, sin frontend. Implementación y operación en
[buscador-noticias-implementacion.md](buscador-noticias-implementacion.md).
Las verificaciones finales se conservan en
[buscador-noticias-generadas-resultados.json](buscador-noticias-generadas-resultados.json).

## Endpoint y validación

`GET /api/publicaciones/buscar/?q=Rovira&page=1`, público y sin sesión/token.
Otros métodos, incluidos HEAD y OPTIONS, devuelven HTTP 405 y `Allow: GET`,
con la respuesta estándar de Django. El listado de portada no cambia.

- `q` obligatorio: normalizar NFC y colapsar espacios Unicode antes de validar.
  Entre 2 y 150 caracteres y hasta 10 términos separados por espacios; no truncar.
- Se admiten tabulación, CR y LF y separadores Unicode habituales, incluido NBSP.
  Se rechazan los demás caracteres de categoría Unicode C.
- Se eliminan términos redundantes de las condiciones, después de plegarlos.
  La consulta devuelta conserva mayúsculas, acentos y repeticiones.
- Comillas, %, _, barras y puntuación son texto literal. No hay operadores,
  comodines introducidos por el usuario, regex, corrección ortográfica ni IA.
- `page` omitido es 1. Se admiten dígitos ASCII, ceros iniciales y hasta 10 dígitos;
  debe ser positivo y estar dentro del rango. Entrada inválida: HTTP 400.

## Semántica

Se buscan todas las Publicacion almacenadas, incluidas las anteriores a las últimas
150 y las que no tienen categoría, departamento ni procesamiento IA. Cada término
debe coincidir parcialmente en título O contenido; los términos se combinan con
AND, sin importar orden ni proximidad. No hay joins que dupliquen publicaciones
ni agrupación de artículos distintos sobre el mismo hecho.

La normalización V1 aplica NFC, minúsculas y traducción de vocales:
`áàâäãåéèêëíìîïóòôöõúùûü` → `aaaaaaeeeeiiiiooooouuuu`.
Cubre acentos del español, diéresis y vocales latinas habituales; conserva ñ/n y
las equivalencias compuestas/descompuestas. No es transliteración universal.
Los originales no se alteran. La misma V1 se utiliza para consulta, almacenamiento
y contexto del extracto; no se usa unaccent.

El motor mantiene `titulo_busqueda` y `contenido_busqueda` como columnas generadas
STORED. Son internas, no editables y no serializables. Las consultas de lectura
omiten su contenido cuando no es necesario y no generan cargas diferidas adicionales.
El endpoint no escribe ni hace llamadas a scraping, ingesta o servicios externos.
Los errores internos no se convierten en cero resultados.

Orden: Coalesce(fecha_publicacion, fecha_captura) descendente, nulos al final y PK
descendente. Se reutiliza core.fechas.datos_fecha, con zona local y precisión de día
para notas de archivo cuando corresponde. fecha_captura es NOT NULL; ambos timestamps
nulos sólo se prueban en un objeto no persistido.

Páginas de 20 noticias. Cero coincidencias en página 1: HTTP 200, lista vacía y total
de páginas 1; cualquier página posterior: HTTP 400. No se limita el universo a portada.

## Respuesta exacta

Claves superiores:

| Campo | Tipo |
|---|---|
| consulta | string normalizado |
| total | entero, coincidencias exactas |
| pagina | entero |
| tamano_pagina | entero, 20 |
| total_paginas | entero |
| anterior, siguiente | URL relativa con q/page o null |
| resultados | lista |

Cada resultado contiene exclusivamente:

| Campo | Tipo y significado |
|---|---|
| id_publicacion_api | PK pública entera |
| titulo, fuente | strings originales |
| fecha_efectiva | ISO local o día ISO según precisión; null sin fecha |
| fecha_dia | día ISO o null |
| fecha_precision | instante, dia o null |
| fecha_origen | publicacion, captura o null |
| detalle_url | URL interna construida con reverse('noticia') |
| imagen_url | propiedad pública existente, local/remota o null |
| extracto | texto plano con contexto, sin resaltado HTML |

El extracto elimina HTML, decodifica entidades, colapsa espacios y usa NFC. Incluye
hasta 240 caracteres más elipsis; comienza hasta 80 caracteres antes de una coincidencia
del contenido. Si sólo coincide el título, puede usar el comienzo. No garantiza límites
de palabra ni contener todos los términos. Los índices del texto plegado se mapean
al original presentado si lower expande caracteres, por ejemplo İ.

No se devuelve contenido completo ni atributos administrativos. Texto y URLs siguen
siendo datos no confiables: el futuro frontend deberá escapar texto y validar los
protocolos de enlaces e imágenes.

Ejemplo de una respuesta sobre datos sintéticos:

```json
{"consulta":"Róvira","total":1,"pagina":1,"tamano_pagina":20,"total_paginas":1,"anterior":null,"siguiente":null,"resultados":[{"id_publicacion_api":15002,"titulo":"Rovira: educación pública","fuente":"El Territorio","fecha_efectiva":"2026-10-23T09:00:00-03:00","fecha_dia":"2026-10-23","fecha_precision":"instante","fecha_origen":"publicacion","detalle_url":"/noticia/15002/","imagen_url":null,"extracto":"Nueva propuesta de educación para Misiones."}]}
```

Errores 400 con códigos estables y mensaje claro:

```json
{"error":{"codigo":"consulta_invalida","mensaje":"q debe tener entre 2 y 150 caracteres y hasta 10 términos."}}
```

```json
{"error":{"codigo":"pagina_invalida","mensaje":"La página está fuera del rango."}}
```

## Operación, pruebas y frontend pendiente

Aplicar `0011_publicacion_texto_busqueda` antes de servir código que consulta los
campos. V1 está congelada en core.busqueda_texto_v1, sin depender de lógica de negocio
mutable. SQLite registra tw_plegar_v1 de forma determinista en cada conexión, antes
de migrar o escribir. La compatibilidad y la reversión se probaron con Django real
en ambos motores; el orden de rollback SQLite difiere del de PostgreSQL.

El validador reproducible usa exclusivamente recursos desechables propios:

```bash
bash tools/buscador/validar_generadas.sh todo > /tmp/generadas.jsonl 2> /tmp/generadas.log
```

La batería y resultados exactos, controles de migración, espacio y posibles bloqueos,
limitaciones de rendimiento y pasos de reversión están en la documentación de
implementación. El JSON de referencia persistido incluido es necesario para que
el validador compare con la consulta original, sin repetir su investigación.

No se implementó interfaz. Quedan formulario, estados de carga/error/vacío,
paginación, accesibilidad y escape de contenido. No se agregan resaltado HTML,
agrupación de hechos ni cambios a clasificación o ingesta.
