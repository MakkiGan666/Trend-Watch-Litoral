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
representantes/resultados editoriales, no filas físicas de publicaciones. Si una
coincidencia está en un miembro distinto de la representante, la fecha de esa
coincidencia conserva la posición del grupo y el extracto se toma de esa versión;
el título y el enlace principal siguen llevando a la representante.

## Contrato API

`GET /api/publicaciones/buscar/?q=...&page=...` mantiene las claves existentes:
`consulta`, `total`, `pagina`, `tamano_pagina`, `total_paginas`, `anterior`,
`siguiente` y `resultados`. Los resultados individuales no agrupados conservan su
forma anterior. Sólo un resultado de grupo activo añade:

```json
{
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

Si el miembro distinto de la representante produjo la coincidencia, se agrega
`coincidencia` con su ID, título, fuente y `detalle_url`. El campo `extracto` se
genera con el texto de esa coincidencia cuando tiene cuerpo completo. El JSON no
expone cuerpos completos. Las publicaciones originales y sus relaciones no se
alteran ni se ocultan; cada `detalle_url` permite consultarlas individualmente.

## Filtros compartidos

La página HTML y las dos APIs aceptan los mismos parámetros:

- `desde=AAAA-MM-DD` y `hasta=AAAA-MM-DD`: límites inclusivos sobre la fecha
  efectiva de cada publicación (editorial, o captura cuando falta la editorial).
- `fuente=...`: coincidencia exacta sin distinguir mayúsculas/minúsculas.
- `categoria=...`: nombre exacto de categoría sin distinguir mayúsculas/minúsculas.

Los filtros se aplican a las publicaciones coincidentes antes de agrupar. La
paginación conserva `q` y los filtros. El autocompletado usa los mismos filtros y
cuenta la frecuencia de cada término por grupo editorial único; las noticias
sugeridas se limitan a una representante por grupo.

## Coste y límites

Las consultas usan el estado persistente y restricciones indexadas de la fase 2A.
El conteo y la página se calculan en SQL. La lectura de versiones originales y,
cuando aplica, de la publicación que produjo la coincidencia usa consultas en
lote con un número fijo de consultas; no hace consultas por resultado. No se
recalcula similitud ni se cargan cuerpos para decidir agrupaciones en cada
solicitud. La cantidad de versiones se mantiene dentro del máximo de 20 miembros
por grupo impuesto al revisar candidatos.

El contrato `total` cambia deliberadamente a resultados editoriales agrupados.
No cambian los endpoints de detalle ni las identidades originales. No se
requiere migración para esta integración.
