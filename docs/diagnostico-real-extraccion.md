# H4.2-E.2 — Diagnóstico de errores reales H4.2-D

Fecha de diagnóstico: 2026-11-06. Rama: `feat/h4-2-diagnostico-real-extraccion`.
Base: `32f83371e56606ee4e337c795c79ced4fc86b611`.

## Recuperación y procedencia de la muestra

Se buscaron las URLs originales en los artefactos locales de H4.2-D. El archivo
temporal `/tmp/tw-h42d/resultados.json` y sus registros ya no existían; el informe
H4.2-D no guarda URLs. Por tanto, no se pudieron recuperar los seis artículos
originales.

Se realizó una **muestra nueva, diferente de H4.2-D**: una descarga de feed por
cada medio y las dos primeras entradas válidas de cada feed actual. H2.1 hizo
3 descargas RSS y 6 descargas HTML, una por artículo, sin reintentos. H2.2
procesó los bytes RSS en memoria y H4.2-E.1 diagnosticó las respuestas HTML.
Las 3 descargas RSS fueron aceptadas, con 10 entradas válidas y 0 rechazos por
feed. Las 6 respuestas HTML se obtuvieron correctamente. No se descargaron
imágenes. Los bytes HTML se descartaron después del diagnóstico; no se
guardaron URLs, títulos ni cuerpos en el informe.

## Resultados por artículo

Los seis casos produjeron `JSONLD`. Cada HTML tenía charset `utf-8`, exactamente
un candidato JSON-LD `Article`/`NewsArticle` y cero scripts JSON-LD malformados.
La identidad declarada resolvió al hostname autorizado de su propia fuente; no
se detectó identidad de otro medio. No hubo errores de canonical por host,
codificación o límites.

| Medio | Artículo de la muestra nueva | Código | Charset | Nodos | Scripts / candidatos JSON-LD | Contenedores | Host declarado |
| --- | ---: | --- | --- | ---: | ---: | --- | --- |
| Misiones Online | 1 | JSONLD | utf-8 | 1.144 | 2 / 1 | 1 `div`, 2.701 caracteres / 409 palabras | `misionesonline.net` |
| Misiones Online | 2 | JSONLD | utf-8 | 1.143 | 2 / 1 | 1 `div`, 2.119 caracteres / 362 palabras | `misionesonline.net` |
| La Misión Digital | 1 | JSONLD | utf-8 | 525 | 1 / 1 | 0 contenedores reconocidos | `lamisiondigital.com` |
| La Misión Digital | 2 | JSONLD | utf-8 | 525 | 1 / 1 | 0 contenedores reconocidos | `lamisiondigital.com` |
| Noticias de Irigoyen | 1 | JSONLD | utf-8 | 506 | 1 / 1 | 0 contenedores reconocidos | `noticiasdeirigoyen.com.ar` |
| Noticias de Irigoyen | 2 | JSONLD | utf-8 | 491 | 1 / 1 | 0 contenedores reconocidos | `noticiasdeirigoyen.com.ar` |

## Lectura de la muestra E.2 y límites de su evidencia

En H2.3, `JSONLD` se emite cuando hay candidatos JSON-LD, pero ninguno queda
asociado a la URL RSS o a la URL canónica validada. Como en los seis casos hubo
un candidato, el rechazo indica que una identidad del candidato no coincidió
con ambas referencias permitidas. Los hostnames informados coinciden con los
hosts autorizados, así que el patrón observado apunta a una diferencia de ruta
o query en la identidad JSON-LD, no a una declaración de otro medio.

La ejecución E.2 no registraba comparaciones por campo ni presencia de canonical.
La nueva medición E.4, abajo, sí las expone; no se volvieron a descargar esos
artículos para reconstruir retrospectivamente sus métricas. Tampoco se midieron
cuerpo, fecha o imagen como resultados de extracción: el rechazo ocurrió antes
de elegir los metadatos finales. Los contenedores vacíos en La Misión Digital y
Noticias de Irigoyen solo significan que no se encontró `articleBody`, selector
conocido, `article` o `main`; no prueban que sus páginas carezcan de texto
editorial.

## Muestra E.4 — medición nueva de discrepancias JSON-LD

Esta es una **nueva ejecución**, posterior a E.2, sobre los feeds actuales y
sus dos primeras entradas válidas por fuente. No se puede garantizar que las
URLs subyacentes sean distintas de E.2: aquellas URLs no se conservaron y no se
compararon ni almacenaron las de esta muestra. La etiqueta «nueva» identifica
esta medición con E.3, no certifica noticias distintas.

H2.1 descargó una vez cada uno de los tres feeds y hasta dos HTML por fuente: 3
RSS y 6 HTML, sin reintentos. Los feeds tuvieron 10 entradas válidas y 0
rechazos cada uno; las seis respuestas HTML llegaron correctamente. Todo el
HTML fue procesado en memoria y descartado. No se guardaron URLs, títulos ni
cuerpos.

| Fuente | Artículo ordinal | Nodos HTML | Charset | Scripts / candidatos / JSON-LD inválidos | Canonical presente / válida / coincide con RSS | Campo `url` | Campo `mainEntityOfPage` | Resultado |
| --- | ---: | ---: | --- | --- | --- | --- | --- | --- |
| Misiones Online | 1 | 1.140 | utf-8 | 2 / 1 / 0 | sí / sí / sí | ausente | presente; host permitido; no coincide con RSS ni canonical | `JSONLD_MAIN_ENTITY_OF_PAGE_NO_COINCIDE_RSS_NI_CANONICAL` |
| Misiones Online | 2 | 1.138 | utf-8 | 2 / 1 / 0 | sí / sí / sí | ausente | presente; host permitido; no coincide con RSS ni canonical | `JSONLD_MAIN_ENTITY_OF_PAGE_NO_COINCIDE_RSS_NI_CANONICAL` |
| La Misión Digital | 1 | 525 | utf-8 | 1 / 1 / 0 | sí / sí / sí | ausente | presente; host permitido; no coincide con RSS ni canonical | `JSONLD_MAIN_ENTITY_OF_PAGE_NO_COINCIDE_RSS_NI_CANONICAL` |
| La Misión Digital | 2 | 525 | utf-8 | 1 / 1 / 0 | sí / sí / sí | ausente | presente; host permitido; no coincide con RSS ni canonical | `JSONLD_MAIN_ENTITY_OF_PAGE_NO_COINCIDE_RSS_NI_CANONICAL` |
| Noticias de Irigoyen | 1 | 506 | utf-8 | 1 / 1 / 0 | sí / sí / sí | ausente | presente; host permitido; no coincide con RSS ni canonical | `JSONLD_MAIN_ENTITY_OF_PAGE_NO_COINCIDE_RSS_NI_CANONICAL` |
| Noticias de Irigoyen | 2 | 491 | utf-8 | 1 / 1 / 0 | sí / sí / sí | ausente | presente; host permitido; no coincide con RSS ni canonical | `JSONLD_MAIN_ENTITY_OF_PAGE_NO_COINCIDE_RSS_NI_CANONICAL` |

La comparación de `url` figura como falsa en las métricas booleanas porque no
había valor que comparar; aquí se informa como **ausente**, no como una
discrepancia. En los seis candidatos, `mainEntityOfPage` sí aportó identidad y
su hostname estaba permitido, pero la URL normalizada no igualó ni la URL RSS
ni la canonical. En cambio, canonical era válida y coincidía con RSS en los
seis. Por eso el rechazo concreto y repetido fue `mainEntityOfPage`, no una
identidad de otro medio, una canonical insegura o codificación/límites.

La diferencia observada es de identidad normalizada. Como no se guardan rutas ni
queries, sigue siendo una hipótesis que represente una ruta/query alternativa o
un alias editorial legítimo; tampoco se puede determinar cuál de los dos medios
publica marcado incorrecto. La muestra no permite extraer conclusiones sobre
cuerpo, fechas o imágenes de estos artículos.

## Muestra E.7 — comparación estructural de una entrada por fuente

Esta medición es distinta de E.2 y E.4: se descargó una vez cada feed y se
seleccionó solo su primera entrada válida actual. H2.1 completó **3 descargas
RSS y 3 HTML**, sin reintentos. Cada feed entregó 10 entradas válidas y 0
rechazos; las tres páginas HTML se recibieron correctamente. No se guardaron
URLs, HTML, títulos, cuerpos, hashes ni valores de fragmento/query.

Los tres casos mantuvieron el subcódigo
`JSONLD_MAIN_ENTITY_OF_PAGE_NO_COINCIDE_RSS_NI_CANONICAL`: `url` estaba ausente;
`mainEntityOfPage` estaba presente y en hostname permitido; canonical estaba
presente, era válida y coincidía con RSS. La comparación E.6 mostró el mismo
patrón estructural en cada medio:

| Medio | `mainEntityOfPage` parseable / normalizable | HTTPS / puerto permitido / hostname permitido / exacto | Path exacto / igual sin barra final | Query exacta / igual sin tracking / solo tracking | Fragmento presente / igual | Esquema, puerto, path, query y host de referencia |
| --- | --- | --- | --- | --- | --- | --- |
| Misiones Online | sí / no | sí / sí / sí / sí | sí / sí | sí / sí / no | sí / no | RSS y canonical coinciden en los componentes sin fragmento |
| La Misión Digital | sí / no | sí / sí / sí / sí | sí / sí | sí / sí / no | sí / no | RSS y canonical coinciden en los componentes sin fragmento |
| Noticias de Irigoyen | sí / no | sí / sí / sí / sí | sí / sí | sí / sí / no | sí / no | RSS y canonical coinciden en los componentes sin fragmento |

La diferencia estructural observable es únicamente el fragmento: la URL de
`mainEntityOfPage` contiene uno y RSS/canonical no; el resto de componentes
comparados coincide. Esto es compatible con un enlace al mismo documento con
ancla, no con una diferencia de host, path, barra final o query. Es una señal
fuerte de alias de mismo recurso, pero no una prueba definitiva de identidad
editorial: los valores no se conservaron y no se puede determinar si el fragmento
representaba un ancla HTML u otra convención del sitio. H2.2 rechaza fragmentos,
por lo que la normalización actual no equipara estas identidades.

La corrección candidata para evaluar en otra etapa sería una equivalencia
limitada al cotejo de identidad JSON-LD cuando todos los componentes seguros
(HTTPS, puerto permitido, host exacto, path y query) coincidan y la única
diferencia sea el fragmento. No aplicarla a URLs descargables, no ampliar
hosts, no aceptar esquemas inseguros y mantener el rechazo si cualquier otro
componente difiere. Esta medición no implementó esa regla.

## Correcciones propuestas, sin implementar

1. **Prioridad alta — mantener el rechazo hasta revisar la semántica del
   fragmento.** E.7 acota el desacuerdo a un fragmento, compatible con ancla al
   mismo documento. Antes de aceptar esa equivalencia hace falta verificar con
   fixture segura qué función editorial tiene el fragmento. No usar solo el host
   como prueba; los artículos siguen rechazados mientras tanto.
2. **Prioridad media — fixture de fragmento exclusivamente.** Reproducir
   canonical=RSS y `mainEntityOfPage` igual en HTTPS, host, path y query, con
   fragmento como única diferencia; comprobar también que diferencias en
   esquema, host, path, barra, query funcional, credenciales o puerto continúen
   rechazándose. Si se aprueba, limitar la equivalencia a la comparación de
   identidad JSON-LD y no a la validación del transporte.
3. **Prioridad posterior — revisar fallback común de cuerpo** para La Misión
   Digital y Noticias de Irigoyen. Primero hace falta una fixture con estructura
   semántica inspeccionable; no agregar selectores de medio a partir de conteos
   vacíos. Misiones Online sí mostró contenedores extensos en esta muestra, pero
   el cuerpo no fue aceptado por el fallo de identidad.

No se modificó el extractor ni las reglas de identidad, aceptación o SSRF. No
hubo ingestas, persistencia, acceso a bases, Gemini ni migraciones.

## Muestra E.9 — validación limitada de equivalencia por fragmento

Medición nueva y separada de E.7, posterior a la corrección E.8. Mediante H2.1
se descargó una vez el RSS de cada medio y se seleccionó como máximo la primera
entrada válida actual: **3 RSS y 3 HTML**, sin reintentos. Cada RSS produjo 10
entradas válidas y 0 rechazos; las tres descargas HTML fueron correctas. El
diagnóstico y la extracción usaron los mismos bytes HTML en memoria. No se
descargaron imágenes ni se guardaron URLs, HTML, títulos, cuerpos, hashes ni
contenido editorial.

| Medio | RSS / HTML | Código / subcódigo | Equivalencia JSON-LD por fragmento | Extracción completa | Cuerpo suficiente | Imagen válida |
| --- | --- | --- | --- | --- | --- | --- |
| Misiones Online | OK / OK | — / — | sí | sí | sí | no |
| La Misión Digital | OK / OK | — / — | sí | sí | no | sí |
| Noticias de Irigoyen | OK / OK | — / — | sí | sí | no | sí |

En los tres casos, `mainEntityOfPage` fue aceptado por la equivalencia acotada
de E.8. El diagnóstico no devolvió código ni subcódigo y el extractor completó
la extracción. Esto resuelve en esta muestra el rechazo JSON-LD observado en
E.7. La extracción completa indica que el extractor devolvió un resultado; no
implica que el cuerpo alcance el umbral existente de 120 caracteres y 20
palabras. Misiones Online sí lo alcanzó; los otros dos resultados quedaron
insuficientes pese a que se detectó una imagen válida.

La selección E.9 es una medición distinta de E.7, pero ambas seleccionaron la
primera entrada válida del feed actual. Como E.7 no conservó URLs y esta
medición tampoco las guarda, no es posible afirmar que los artículos subyacentes
sean distintos; la comparación es entre ejecuciones y resultados observados,
no entre identidades de artículo verificadas.

No hubo cambios en código, reglas de aceptación, persistencia ni SSRF. No se
accedió a bases de datos ni se invocó Gemini.
