# H5.11 — extracción multifuente de artículos completos

## Estado del experimento

Validación técnica puntual en `feat/ingesta-multifuente-experimental`, basada en
`9603a96af14e40f9135454d8e446b16005aa686b`. Una muestra actual por medio se
descargó mediante H2.1 solo después de comprobar `robots.txt`; feed y artículo se
procesaron en memoria. No se guardaron cuerpos, imágenes ni publicaciones. Las
comparaciones con Newspaper3k reutilizaron exactamente los mismos bytes y no
permitieron solicitudes independientes. El PostgreSQL utilizado fue efímero y
solo guardó los controles H5.6; no se consultó ni modificó PostgreSQL habitual.

## Arquitectura implementada

- H2.2 obtiene referencias de imagen de `enclosure`, Atom enclosure,
  `media:content` y `media:thumbnail` cuando el tipo y el host son admitidos.
- H2.3 admite `og:image`, `twitter:image` y `twitter:image:src`. Newspaper3k
  0.2.8 funciona como fallback sobre los mismos bytes con `set_html()`, sin
  `download()`, NLP ni descarga de imágenes.
- `hosts_imagenes_permitidos` es independiente de `hosts_permitidos`. Los CDN
  autorizados para referencias son `elterritorio-s3.cdn.net.ar`,
  `noticiasdelacalle-s3.cdn.net.ar`, `cdn3.stopenlinea.com.ar` y, para Misiones
  Online, `static.misionesonline.news`. Ninguno autoriza descargar HTML.
- La calidad del cuerpo se valida por diversidad léxica, separación del título y
  resumen, estructura mínima de prosa y límites de tamaño. Persistencia vuelve a
  validar; longitud por sí sola no habilita un artículo.
- H4.1 reserva H5.6 antes de cada GET, tanto para feed como para artículo, y
  guarda el intervalo después de cada respuesta. No mantiene una transacción
  abierta durante HTTP. Un 403 detiene la fuente y requiere revisión manual; un
  429 persiste `Retry-After` o el respaldo, y no reintenta esa fuente. Si no se
  puede guardar el estado, queda bloqueada en `EN_CURSO`. Los errores de una
  fuente no detienen las siguientes.
- La identidad se calcula con fuente y URL RSS normalizada. Se consultan hash,
  alias y URLs históricas; los conflictos entre varias publicaciones se informan,
  no se fusionan. Una coincidencia no sobrescribe la publicación existente.
- El intervalo configurado también se respeta entre el GET del feed y cada GET
  de artículo. Si el intervalo es largo, el proceso puede permanecer esperando;
  H5.8 todavía no checkpointa el HTML ya descargado. Una interrupción puede
  requerir volver a obtener el feed después del cooldown.

## Medios con validación técnica puntual

Los once siguientes devolvieron `robots.txt`, feed y artículo HTTP 200; los
paths consultados estaban permitidos por el parser de robots. La muestra fue de
un artículo por medio y no acredita una tasa estadística ni permiso de uso
persistente.

| Medio | Resultado del extractor actualizado | Salvedad de la muestra |
|---|---|---|
| Noticias del 6 | Título, fecha, canónica, imagen y cuerpo válidos | Cuerpo: 1.296 caracteres; heurística editorial aprobada |
| Norte Misionero | Los cinco campos disponibles y cuerpo aprobado | Cuerpo: 8.118 caracteres |
| Noticias de la Calle | Los cinco campos disponibles y cuerpo aprobado | Imagen referenciada en `noticiasdelacalle-s3.cdn.net.ar` |
| Stop en Línea | Los cinco campos disponibles y cuerpo aprobado | Cuerpo corto: 480 caracteres / 53 palabras; requiere revisión de muestra mayor |
| Misiones Online | Los cinco campos disponibles después de permitir su CDN de imagen | `og:image` y `twitter:image` usan `static.misionesonline.news`; título HTML difirió del título RSS en la muestra |
| INFOBER | Los cinco campos disponibles y cuerpo aprobado | Cuerpo: 744 caracteres |
| OberaOnline | Los cinco campos disponibles y cuerpo aprobado | Cuerpo: 4.036 caracteres |
| E24N | Los cinco campos disponibles y cuerpo aprobado | Cuerpo: 1.387 caracteres |
| Radio Yguazú | Los cinco campos disponibles y cuerpo aprobado | Newspaper3k no extrajo fecha del HTML; la fecha disponible provino de RSS |
| La Misión Digital | Los cinco campos disponibles y cuerpo aprobado | Cuerpo: 3.395 caracteres |
| Iguazú Ahora | Los cinco campos disponibles y cuerpo aprobado | Cuerpo: 2.437 caracteres |

“Cuerpo aprobado” se refiere al criterio automático de H2.3, no a una lectura
editorial humana. No se descargó ningún recurso de imagen. Newspaper3k no mejoró
de forma consistente la extracción frente al extractor actual en estas muestras;
en varios casos entregó el mismo cuerpo. Para Misiones Online, la referencia del
CDN se volvió a probar en una página real después del ajuste de allowlist, sin
solicitar el archivo de imagen.

## Casos no probados o fuera de alcance

- **Alem News:** la conexión TLS falló al consultar `robots.txt`; no se reintentó.
- **El Territorio:** su integración periódica sigue pospuesta. El catálogo lo
  conserva como fuente histórica y el scraper legacy no se modificó. Los términos
  públicos requieren consentimiento escrito para reproducir contenido; no se
  descargó HTML en esta etapa.
- **Eldorado Noticias:** no se consultó por la directiva `Visit-time` documentada,
  cuya zona horaria no está resuelta.
- **Fracrán Noticias:** no se consultó por los términos publicados sobre
  consentimiento para usos distintos del personal y no comercial.

No se añadieron fuentes nuevas al catálogo: se conserva el catálogo preexistente
de 18 entradas, todas deshabilitadas. La lista de once medios de arriba delimita
el alcance técnicamente demostrado para la primera versión; los otros elementos
del catálogo no quedan validados por esta lista.

## Condiciones antes de habilitar una fuente

Para cada fuente, por separado:

1. Revisar nuevamente robots, redirecciones, límites de frecuencia y condiciones
   publicadas de consulta automatizada.
2. Aclarar el alcance permitido para almacenar y mostrar título, URL, fecha,
   imagen y cuerpo completo; la aprobación interna no representa permiso del
   titular.
3. Revisar una muestra editorial mayor, en especial el cuerpo corto de Stop en
   Línea, la variación de título de Misiones Online y la procedencia RSS de la
   fecha de Radio Yguazú.
4. Establecer aprobación operativa explícita, fuente habilitada, límite e
   intervalo H5.6 no menores a los publicados. Mantener Gemini deshabilitado
   hasta una autorización independiente.
5. Hacer primero un ensayo aislado; solo una aprobación posterior habilitaría
   una ejecución en la base habitual.

## Validación automatizada

El conjunto focalizado de extractor, parser RSS, persistencia, orquestador y
catálogo se ejecuta contra PostgreSQL/PostGIS temporal. Incluye separación de
hosts de imagen/artículo, identidad y alias, fallos por fuente, cooldown durable,
403, 429 y ausencia de Gemini por defecto. En esta revisión conjunta aprobaron
149 pruebas. Django reportó que el system check no encontró problemas. No se
requiere una migración nueva.

## Alcance de El Territorio

El circuito legacy de El Territorio no se modificó. Su integración en el
orquestador RSS de artículos completos queda pospuesta y requiere diseño y
revisión independiente, sin cambiar la identidad ni el procesamiento histórico.
