# H4.2-D — Validación real de feeds y artículos

Fecha de pasada: 2026-11-06 (hora local Argentina). Rama: `feat/h4-2-validacion-real-fuentes`, base `cf87c2554094af13de0cacd04430ba18eb15d4ef`.

## Método y límites

Se recorrieron una sola vez los 18 feeds configurados en H1.1, sin habilitarlos. Para cada feed se realizó una descarga y se procesó el cuerpo en memoria con H2.2. Se intentó extraer como máximo las dos primeras noticias normalizadas con H2.3, descargando cada página únicamente mediante H2.1. No se siguió la URL canónica con otra petición ni se descargaron imágenes. H2.1 aplicó HTTPS/TLS, DNS público, hosts exactos por fuente, timeout de hasta 10 s, máximo de 1.500.000 bytes por respuesta y hasta cuatro redirects. Ninguna respuesta superó el límite.

El ejecutor usó código montado de solo lectura, SQLite `:memory:` sin consultas ni escrituras, `GEMINI_API_KEY` vacío, sin Gemini, sin modelos de ingesta y sin llamadas directas fuera del transporte. Solo se guardaron conteos, booleanos, tamaños, tiempos y tipos de excepción; este informe no contiene URLs de artículos ni texto editorial. No se reintentó ninguna solicitud.

Totales: **18/18 feeds descargados y aceptados**, 0 errores DNS/HTTP/TLS, 0 XML malformados y 0 entradas RSS rechazadas; 36 artículos intentados y 30 extracciones completadas. Se transfirieron 1.709.317 bytes de feeds y 6.652.527 bytes de HTML (8.361.844 bytes en total). Las 36 entradas tenían título no vacío y fecha RSS válida. En las 30 extracciones completadas, el título y una fecha final estuvieron disponibles; H2.3 permite usar como fallback la fecha RSS, por lo que esta pasada no demuestra que la fecha estuviera presente en HTML. En 13/30 artículos el cuerpo alcanzó el mínimo H2.3 (120 caracteres y 20 palabras). Todas las URLs canónicas validadas y las identidades editoriales de las extracciones completadas correspondieron a sus hosts/fuentes configurados. No se descargó ninguna imagen; en las URLs de imagen extraídas, cuando hubo, la validación de host fue satisfactoria.

`ValueError` en los dos artículos de Misiones Online, La Misión Digital y Noticias de Irigoyen impidió completar extracción. El ejecutor retuvo deliberadamente solo el tipo de excepción, no el mensaje ni el HTML; no puede atribuir la causa más específica a XML, identidad, estructura o parser sin repetir la solicitud. No hubo errores HTTP, DNS ni TLS observados.

## Resultado por medio

`Cuerpo` indica extracciones con contenido suficiente sobre los dos artículos intentados. `Imágenes` cuenta URLs principales encontradas y validadas; una imagen ausente no significa que se haya rechazado una URL. Las fechas están disponibles tras H2.3 y su fallback, no necesariamente en el HTML.

| Fuente | Feed / entradas | Artículos extraídos | Cuerpo suficiente | Imágenes validadas | Error de extracción | Estado |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Misiones Online | OK / 10 | 0/2 | 0/2 | — | 2 × ValueError | REQUIERE AJUSTES |
| Primera Edición | OK / 20 | 2/2 | 0/2 | 0/2 | — | REQUIERE AJUSTES |
| Noticias de la Calle | OK / 30 | 2/2 | 2/2 | 0/2 | — | REQUIERE AJUSTES |
| Noticias del 6 | OK / 10 | 2/2 | 2/2 | 2/2 | — | APTO |
| INFOBER | OK / 30 | 2/2 | 0/2 | 2/2 | — | REQUIERE AJUSTES |
| OberaOnline | OK / 16 | 2/2 | 0/2 | 2/2 | — | REQUIERE AJUSTES |
| Oberá Inside | OK / 30 | 2/2 | 1/2 | 2/2 | — | REQUIERE AJUSTES |
| Stop en Línea | OK / 30 | 2/2 | 2/2 | 0/2 | — | REQUIERE AJUSTES |
| E24N | OK / 10 | 2/2 | 0/2 | 2/2 | — | REQUIERE AJUSTES |
| Eldorado Noticias | OK / 10 | 2/2 | 2/2 | 2/2 | — | APTO |
| Norte Misionero | OK / 20 | 2/2 | 2/2 | 2/2 | — | APTO |
| La Voz de Cataratas | OK / 10 | 2/2 | 0/2 | 2/2 | — | REQUIERE AJUSTES |
| Iguazú Ahora | OK / 10 | 2/2 | 0/2 | 2/2 | — | REQUIERE AJUSTES |
| Radio Yguazú | OK / 10 | 2/2 | 0/2 | 2/2 | — | REQUIERE AJUSTES |
| Alem News | OK / 10 | 2/2 | 0/2 | 2/2 | — | REQUIERE AJUSTES |
| La Misión Digital | OK / 10 | 0/2 | 0/2 | — | 2 × ValueError | REQUIERE AJUSTES |
| Fracrán Noticias | OK / 30 | 2/2 | 2/2 | 2/2 | — | APTO |
| Noticias de Irigoyen | OK / 10 | 0/2 | 0/2 | — | 2 × ValueError | REQUIERE AJUSTES |

### Criterio de clasificación

- **APTO:** feed procesable; dos de dos artículos extraídos; ambos con título, fecha disponible, URL canónica válida, identidad editorial coincidente y cuerpo suficiente; URLs de imagen presentes válidas. Es aptitud para considerar un piloto individual acotado, no autorización para producción masiva.
- **REQUIERE AJUSTES:** uno o más de esos criterios no se cumplieron o la extracción falló. Requiere fixture representativo y cambio evaluado antes de reconsiderar.
- **NO DISPONIBLE:** feed inaccesible o no procesable en esta única pasada. Ninguna fuente quedó en esta categoría.

La ausencia de imagen reduce la cobertura observada y se consigna, aunque no se intentó recuperar una imagen por fuera del HTML. La muestra de dos artículos no permite certificar una tasa estadística de calidad ni variaciones entre secciones o formatos.

## Orden recomendado para revisión y piloto

Primero someter a aprobación y luego considerar un piloto de una fuente por vez, manteniendo las otras deshabilitadas:

1. Noticias del 6.
2. Eldorado Noticias.
3. Fracrán Noticias.
4. Norte Misionero.
5. Noticias de la Calle y Stop en Línea (cuerpo suficiente, pero sin URL de imagen observada en la muestra).
6. Oberá Inside (solo un cuerpo suficiente en dos).
7. INFOBER, OberaOnline, E24N, La Voz de Cataratas, Iguazú Ahora, Radio Yguazú, Alem News y Primera Edición (ningún cuerpo suficiente en la muestra).
8. Misiones Online, La Misión Digital y Noticias de Irigoyen (resolver primero los errores de extracción).

Este orden es provisional y prioriza compatibilidad técnica observada, no calidad editorial ni condiciones de acceso. Antes de activar incluso una fuente APTO: aprobar sus condiciones de acceso, guardar fixtures sin contenido sensible, revisar alias/históricos y cumplir las puertas operativas y de Gemini descritas en H4.2-A/B/C. Todas las fuentes permanecen deshabilitadas.

## Límites de la conclusión

Los resultados reflejan solo esta pasada del 6 de noviembre de 2026. Los feeds y artículos pueden cambiar; no se probaron todas las entradas ni formatos. La validación de canonical es sintáctica y de host, no una segunda descarga. `fecha_extraida` puede ser fallback RSS; no se comparó el valor contra una fuente editorial independiente. No se midió calidad semántica de titulares, duplicados históricos ni precisión de identidad más allá de host/fuente declarados por H2.3. No hubo almacenamiento Django, Gemini, migraciones ni cambios a catálogo/configuración.
