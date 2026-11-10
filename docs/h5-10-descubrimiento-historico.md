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

## Contrato offline con H5.8 (H5.10-D)

El descubridor sigue entregando **URLs candidatas**, no publicaciones ni
entradas aprobadas. H5.10-D añade
`core.services.contrato_historico_lotes.adaptar_candidatas()`, una conversión
pura sin HTTP ni base de datos. Acepta, para cada URL, una verificación separada
que declare `url_verificada`, `tipo=NOTICIA`, `estado_validacion=VERIFICADA`,
título, fecha editorial con zona horaria y procedencia explícita del título y
de la fecha. Registros sin verificación, título o fecha confiable se rechazan.
`lastmod` permanece identificado como dato del sitemap y nunca satisface el
campo editorial.

El resultado es `EntradaHistoricaProcesable`: incluye un `NoticiaRSS` con
fuente, URL validada, título y fecha normalizada a UTC; resumen, contenido y
sección quedan vacíos. Conserva aparte el estado de validación, el índice de
descubrimiento, `lastmod` y la procedencia declarativa. Deduplica por la clave de
identidad URL de H2.1 y aplica la validación de host existente. No obtiene ni
autentica evidencia: la marca de verificación debe provenir de una futura capa
permitida y revisable.

Esta representación tiene la forma de los metadatos H2.2/H5.4. El Territorio se
mantiene fuera del catálogo de feeds y cuenta con una configuración histórica
sin URL de feed, deshabilitada por defecto. No se puede usar para una solicitud
RSS ni para el transporte H2.1.

H5.10-F añade `lotes_rss_metadatos.iniciar_lote_historico()`, que acepta
únicamente `EntradaHistoricaProcesable`, aplica las barreras de fuente y crea
un snapshot durable sin GET. El trabajo conserva `origen=HISTORICO` y la
procedencia por separado. La creación de trabajo, auditoría y snapshot es
atómica; el procesamiento reutiliza los checkpoints, fencing, pausa,
reanudación y deduplicación H5.8/H5.4. No se modifica el control de frecuencia
H5.6 porque no hubo solicitud.

## Límites operativos y de uso

El catálogo H1.1 no contiene `el_territorio`; el legacy mantiene una ruta
independiente. Este parser no amplía ese catálogo ni invoca
`ingestar_historico`, que tiene comportamiento distinto y puede extraer el
cuerpo, clasificar y persistir.

Los términos públicos de El Territorio indican que la reproducción de sus
contenidos requiere autorización previa por escrito. Este trabajo no consulta
sitemaps reales ni determina si las URLs, títulos o metadatos pueden
almacenarse o exhibirse. Las pruebas solo demuestran validaciones con datos
sintéticos; no acreditan autenticidad ni permisos. No habilitar una importación
real hasta resolver esas condiciones y definir frecuencia, retención y campos
permitidos. No demuestra disponibilidad ni cobertura temporal actual del
sitemap.

## Pruebas y ejecución

Las pruebas del descubridor y contrato usan XML y metadatos JSON sintéticos en
`core/fixtures/historico_sitemap/`. Las pruebas de H5.10-F usan entradas
sintéticas y requieren PostgreSQL/PostGIS temporal para verificar trabajos y
checkpoints; no consultan red ni medios externos.
