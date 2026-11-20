# Búsqueda con agrupaciones editoriales

La búsqueda pública (`GET /buscar/` y `GET /api/publicaciones/buscar/`) y el
autocompletado (`GET /api/publicaciones/sugerencias/`) consumen la infraestructura
de agrupación editorial de la fase 2A. No se crean, aprueban, revocan ni modifican
grupos desde estas rutas.

## Qué se agrupa

Una publicación se representa por la publicación elegida en el grupo sólo cuando
su membresía está `APROBADO` y `vigente=True`, y el grupo está `ACTIVO`. Los
miembros pendientes, rechazados, no vigentes y los grupos revocados siguen siendo
resultados independientes. Las publicaciones sin agrupación tampoco cambian.
La búsqueda no infiere grupos, no compara cuerpos y no forma relaciones
transitivas. La creación editorial existente exige que las publicaciones sean del
mismo medio y cada miembro se revisa directamente contra la representante.

La agrupación ocurre en la consulta antes del `COUNT`, el ordenamiento final y la
paginación. Por tanto, `total`, `total_paginas` y los enlaces de navegación cuentan
resultados editoriales, no filas físicas de publicaciones. Los términos y filtros
se aplican primero a cada publicación. Cada grupo elegible conserva una única
identidad estable: el ID y la representante
aprobada del grupo. La versión presentada se elige entre las publicaciones que
superaron todos los términos y filtros: fecha efectiva más reciente y, ante un
empate, ID mayor. Ese mismo orden determina la relevancia y la posición del grupo.
Por eso, la fecha, categoría, imagen, título y fragmento visibles pertenecen a la
versión que satisfizo la búsqueda. La representante y todas las versiones
originales siguen accesibles mediante enlaces explícitos.

## Contrato API

`GET /api/publicaciones/buscar/?q=...&page=...` mantiene las claves existentes:
`consulta`, `total`, `pagina`, `tamano_pagina`, `total_paginas`, `anterior`,
`siguiente` y `resultados`. Los resultados individuales no agrupados conservan su
forma anterior. En un grupo, `id_publicacion_api` conserva el ID estable de la
representante; los campos de presentación y `detalle_url` corresponden a la
versión seleccionada. Se agregan `id_publicacion_presentada`, `representante` y
`categorias`, además de las versiones originales:

```json
{
  "id_publicacion_api": 10,
  "id_publicacion_presentada": 12,
  "titulo": "Título de la versión seleccionada",
  "fecha_efectiva": "2026-11-19T12:00:00-03:00",
  "categorias": ["Salud"],
  "detalle_url": "/noticia/12/",
  "representante": {
    "id_publicacion_api": 10,
    "titulo": "Título de la representante",
    "fuente": "Noticias del 6",
    "detalle_url": "/noticia/10/"
  },
  "versiones_originales": [
    {
      "id_publicacion_api": 12,
      "titulo": "Título de la versión",
      "fuente": "Noticias del 6",
      "detalle_url": "/noticia/12/"
    }
  ]
}
```

Si la versión seleccionada difiere de la representante, se agrega `coincidencia`
con el ID, título, fuente y `detalle_url` de esa versión. El campo `extracto` se
genera con su texto cuando tiene cuerpo completo. El JSON no expone cuerpos
completos. El autocompletado también sugiere la versión elegible y, para grupos,
incluye la identidad y el enlace de la representante. Las publicaciones
originales y sus relaciones no se alteran ni se ocultan.

## Filtros compartidos

La página HTML y las dos APIs aceptan los mismos parámetros:

- `desde=AAAA-MM-DD` y `hasta=AAAA-MM-DD`: límites inclusivos sobre la fecha
  efectiva de cada publicación (editorial, o captura cuando falta la editorial).
- `fuente=...`: coincidencia exacta sin distinguir mayúsculas/minúsculas.
- `categoria=...`: nombre exacto de categoría sin distinguir mayúsculas/minúsculas.

Los filtros se aplican a las publicaciones coincidentes antes de agrupar. La
presentación siempre usa una versión que cumple todos los filtros activos, por
lo que la fecha y categoría visibles corresponden al resultado filtrado. La
paginación conserva `q` y los filtros. El autocompletado usa los mismos filtros y
cuenta la frecuencia de cada término por grupo editorial único; las noticias
sugeridas se limitan a una versión por grupo.

## Coste y límites

Las consultas usan el estado persistente y restricciones indexadas de la fase 2A.
El conteo y la página se calculan en SQL. La lectura de la presentación, sus
categorías y las versiones originales usa consultas en lote con un número fijo;
no hace consultas por resultado. No se recalcula similitud ni se cargan cuerpos
para decidir agrupaciones en cada solicitud. La cantidad de versiones se mantiene
dentro del máximo de 20 miembros
por grupo impuesto al revisar candidatos.

El contrato `total` cambia deliberadamente a resultados editoriales agrupados.
No cambian los endpoints de detalle ni las identidades originales. No se
requiere migración para esta integración.
