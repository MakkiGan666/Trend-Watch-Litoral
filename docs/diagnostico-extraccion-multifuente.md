# Diagnóstico estructurado H2.3

`extractor_articulos.ErrorExtraccion` hereda de `ValueError`, por lo que los
llamadores existentes que capturan `ValueError` conservan su comportamiento.
Además expone `codigo` y `metricas`; el mensaje es genérico y no contiene texto
del artículo. Los códigos estables son `IDENTIDAD_EDITORIAL`, `URL_CANONICA`,
`JSONLD`, `CODIFICACION`, `HTML_INVALIDO` y `LIMITE_PROCESAMIENTO`.

Las métricas contienen únicamente hostname (nunca URL completa), charset,
conteo de nodos, scripts y candidatos JSON-LD, cantidad de JSON-LD inválido,
cantidad de canonicals sintácticamente inválidos y longitudes por contenedor
(índice, etiqueta HTML, caracteres y palabras). El resumen de éxito añade
banderas de presencia y longitudes del cuerpo, pero no título, resumen ni
cuerpo. No se deben registrar el HTML, el `ArticuloExtraido`, el mensaje de
excepciones ajenas a `ErrorExtraccion` ni objetos `NoticiaRSS`.

Para rechazos JSON-LD, `ErrorExtraccion.subcodigo` y el campo `subcodigo` del
resumen diferencian discrepancias de `url` y `mainEntityOfPage`, así como
hostnames no permitidos. `metricas.identidades_jsonld` contiene como máximo diez
registros con presencia de campos y comparaciones booleanas frente a URL RSS,
canonical y referencia final. También registra si canonical está presente,
válida y coincide con URL RSS. Nunca incluye rutas ni URLs. Los hostnames
declarados solo se incluyen si pertenecen a la política permitida; ante un host
ajeno se registra `hostname_declarado_permitido: false` sin revelar el host.
Cada identidad añade banderas estructurales para parseo/normalización, HTTPS,
puerto permitido, hostname autorizado, credenciales y fragmento. Frente a RSS y
canonical registra igualdad de esquema, puerto, hostname exacto, path, path sin
una barra final, query literal, query tras quitar únicamente tracking conocido,
si la diferencia es solo ese tracking, fragmento y resultado de normalización.
No conserva componentes ni valores de query. Los subcódigos describen rechazos,
no alteran la autorización ni los criterios de aceptación.

## Diagnóstico dirigido sin persistencia

Con una `NoticiaRSS` ya obtenida y los bytes HTML ya disponibles en memoria,
llamar a `diagnosticar_articulo(datos_html, noticia, fuente)` devuelve un
diccionario resumido. No usa ORM, no guarda noticias ni realiza descargas. Para
una futura revisión autorizada de una fuente, se puede obtener el feed y un
solo artículo con H2.1, procesar el feed en memoria con H2.2 y pasar esos bytes
a esta función. No se debe repetir una pasada de las 18 fuentes para obtener
diagnósticos.

Ejemplo de inspección segura:

```python
from core.services.extractor_articulos import diagnosticar_articulo

resumen = diagnosticar_articulo(html_bytes, noticia_rss, fuente_catalogo)
print(resumen)  # Sólo códigos, métricas estructurales y banderas.
```

Para agregar métricas de varios artículos, acumular sólo `codigo`, hostname y
contadores. Los hostnames declarados que aparezcan en `hostname_declarado`
deben tratarse como dato de diagnóstico, nunca como permiso para ampliar la
política de hosts. Los valores inseguros siguen rechazándose; este mecanismo
no cambia extracción, identidad, aceptación, límites ni controles SSRF.
