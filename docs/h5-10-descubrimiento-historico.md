# H5.10-B — Descubrimiento histórico offline por sitemap

## Alcance

`core.services.descubrimiento_historico_sitemap.descubrir(documento, limite=20)`
analiza bytes XML locales de un sitemap con estructura estándar. No tiene
transporte HTTP, no abre bases de datos, no persiste resultados y no descarga
páginas de artículos. La entrada debe ser suministrada expresamente por el
operador o por una futura capa de transporte independiente.

El prototipo admite `sitemapindex` y `urlset`, con o sin el namespace estándar
de Sitemap. Valida cada URL con `descarga_segura.validar_url()` y la identidad
normalizada existente de H2.1, que para este prototipo restringe destinos a
`elterritorio.com.ar` y `www.elterritorio.com.ar`. Rechaza XML vacío o mayor de
2 MB, límites fuera de 1–100, URLs superiores a 500 caracteres, DTD y
declaraciones de entidades. No consulta ni resuelve referencias externas.

En un índice devuelve referencias de sitemaps como `SITEMAP_PENDIENTE` y marca
`descarga_automatica: false`; nunca los sigue. En un `urlset` solo propone como
candidatas las rutas que coinciden con el patrón `/noticias/YYYY/MM/DD/ID-slug`
conocido por el parser legacy. Esta coincidencia es un filtro de forma, no una
verificación editorial: `verificada_como_noticia` permanece `false`.

## Salida

La salida serializable incluye `fuente_id`, tipo de documento, límite, URLs
candidatas o sitemaps pendientes, URLs válidas que no coinciden con el patrón,
rechazos por código, duplicados y elementos que exceden el límite. Los
elementos conservan `lastmod` solo si su formato de fecha ISO es válido y
separan `lastmod_estado`. **`lastmod` nunca se asigna a `fecha_publicacion`.**
No se incluyen títulos, descripciones, contenido, imágenes ni clasificaciones.

Ejemplo de una candidata:

```json
{
  "estado": "CANDIDATA_NO_VERIFICADA",
  "fecha_publicacion": null,
  "indice": 0,
  "lastmod": "2026-10-02T10:30:00Z",
  "lastmod_estado": "VALIDO",
  "url": "https://www.elterritorio.com.ar/noticias/2026/10/01/12345-titular-de-prueba",
  "verificada_como_noticia": false
}
```

`limite` acota las candidatas emitidas (o referencias de índice). Los elementos
adicionales elegibles se contabilizan en `fuera_limite`; los rechazos y
duplicados también se informan aparte. El XML completo se analiza dentro del
límite de bytes para que el recuento no dependa de truncar silenciosamente el
documento.

## Relación con H5.8

El resultado **no se puede entregar directamente** a H5.8: el trabajo por lotes
requiere metadatos de publicación, en particular un título RSS auténtico. Antes
de construir una entrada para H5.8, cada URL tendría que verificarse como una
noticia mediante una fuente de índice autorizada que proporcione título y fecha,
o mediante una futura revisión permitida del artículo. Una fecha de ruta o
`lastmod` no sustituye por sí sola a la fecha editorial. La capa de integración
futura debería convertir únicamente candidatos revisados a un snapshot H5.8 y
reutilizar sus checkpoints, alias, deduplicación y límites por fuente.

## Límites operativos y de uso

El catálogo H1.1 no contiene `el_territorio`; el legacy mantiene una ruta
independiente. Este parser no amplía ese catálogo ni invoca
`ingestar_historico`, que tiene comportamiento distinto y puede extraer el
cuerpo, clasificar y persistir.

Los términos públicos de El Territorio indican que la reproducción de sus
contenidos requiere autorización previa por escrito. Este prototipo offline no
consulta sitemaps reales ni determina si las URLs, títulos o metadatos pueden
almacenarse o exhibirse. No debe conectarse a un proveedor real ni integrarse
con H5.8 hasta resolver esa condición y definir frecuencia, retención y campos
permitidos. No demuestra disponibilidad ni cobertura temporal actual del
sitemap.

## Pruebas y ejecución

Las pruebas usan exclusivamente XML sintético en
`core/fixtures/historico_sitemap/`; se ejecutan con `python -m unittest
core.test_descubrimiento_historico_sitemap` desde `app/`. No requieren PostgreSQL,
Docker, red, sitemaps externos ni artículos.
