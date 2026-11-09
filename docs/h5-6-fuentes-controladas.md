# H5.6-A — preparación de fuentes RSS controladas

## Política operativa

H5.4 persiste exclusivamente `fuente`, título RSS, URL normalizada y fecha
interpretable. No guarda descripción, cuerpo, imagen ni clasificación. Antes
de cualquier GET, H5.6 exige habilitación técnica
(`RSS_METADATOS_FUENTES_HABILITADAS`), revisión de acceso
(`RSS_METADATOS_FUENTES_REVISADAS`), aprobación operativa interna
(`RSS_METADATOS_FUENTES_APROBADAS_POR_EQUIPO`), límite e intervalo por fuente y
`--confirmar-persistencia` para esa ejecución. Estas listas y mapas están
vacíos por defecto. La aprobación del equipo registra una decisión interna de
uso de metadatos; no afirma que el medio o titular haya concedido permiso ni
resuelve restricciones de acceso o reutilización.

`RSS_METADATOS_FUENTES_PERMISO_TITULAR_EXPRESO_VERIFICADO` es un registro
documental aparte, vacío por defecto. Sólo se incluyen IDs con evidencia
verificable de autorización expresa del titular. No habilita la fuente, no
satisface la aprobación del equipo y su ausencia no prueba ni permiso ni
prohibición. No se configura para Noticias del 6 en esta etapa.
La variable anterior `RSS_METADATOS_FUENTES_AUTORIZADAS` deja de leerse; no se
debe copiar automáticamente a ninguna de las dos variables nuevas.

Los mapas se expresan como JSON de ID a entero positivo. El límite no puede
superar cinco. El intervalo se mide entre intentos y se registra antes del GET
en `ControlSolicitudRSSMetadatos`, bajo el advisory lock H3.1 compartido por
fuente. Antes del GET se confirma `EN_CURSO`; la transacción termina antes de la
red. Al guardar el resultado se cambia a `ESPERA` con el mayor entre el intervalo
mínimo y el `Retry-After`. Un HTTP 429 sin valor válido usa 24 horas
(configurable con `RSS_METADATOS_429_SIN_RETRY_AFTER_SEGUNDOS`). H2.1 no reintenta.
Una repetición prematura devuelve `BLOQUEADA` y no hace GET.

Si el proceso se interrumpe o la base falla al cerrar el resultado/bloqueo, la
reserva queda durable en `EN_CURSO`; no vence automáticamente. Si `Retry-After`
excede 365 días, el estado pasa a `REVISION_MANUAL`, nunca se acorta el plazo.
Ambos estados bloquean nuevos GET. La recuperación requiere revisión humana del
estado del proceso, la respuesta del servidor y las condiciones de acceso; luego
se ejecuta explícitamente:

```sh
python manage.py resolver_bloqueo_rss_metadatos --fuente ID --confirmar-revision-manual
# Sólo si el estado es REVISION_MANUAL por Retry-After > 365 días, y tras comprobar
# que venció el plazo original, agregar también:
# --confirmar-retry-after-vencido
```

Este comando no consulta la fuente. Sólo cambia el estado a `ESPERA` y añade un
intervalo completo desde la resolución; no permite una consulta inmediata. Para
un `Retry-After` excesivo, antes debe haber vencido el plazo original y se exige
además `--confirmar-retry-after-vencido`. La confirmación es una operación
manual del responsable después de verificar la restricción del servidor.

Ejemplo de **contrato futuro**, no autorización ni fuente habilitada:

```sh
RSS_METADATOS_FUENTES_HABILITADAS=ID \
RSS_METADATOS_FUENTES_REVISADAS=ID \
RSS_METADATOS_FUENTES_APROBADAS_POR_EQUIPO=ID \
RSS_METADATOS_FUENTES_PERMISO_TITULAR_EXPRESO_VERIFICADO= \
RSS_METADATOS_LIMITES_POR_FUENTE='{"ID":1}' \
RSS_METADATOS_INTERVALOS_SEGUNDOS_POR_FUENTE='{"ID":1800}' \
python manage.py ingestar_rss_metadatos --fuente ID --limite 1 --confirmar-persistencia
```

La revisión de acceso debe registrar por separado las condiciones de consulta
y las del almacenamiento/presentación de título, fuente, fecha y enlace. Un RSS
público o `robots.txt` no concede por sí solo derechos de reutilización. Si la
revisión concluye que se necesita autorización del titular, no se aprueba la
fuente hasta resolverlo. Una autorización expresa, cuando exista, se registra
por separado y se conserva su evidencia. Nunca se infiere desde una decisión
interna.

## Matriz conocida al 2026-11-08

Los resultados técnicos proceden de una sola pasada documentada en
[`validacion-real-fuentes.md`](validacion-real-fuentes.md) (06/11/2026) y de las
previsualizaciones H4.8 registradas en el historial del proyecto. Esta matriz
no autoriza persistencia ni republicación. El lector RSS observó título, enlace
y fecha interpretable en las cuatro entradas H1.1; también había campos
adicionales, pero H5.4 los descarta. La normalización conserva esquema HTTPS,
host exacto, path y query funcional; elimina únicamente parámetros de tracking
conocidos. No une `www` con apex ni distintas rutas.

| Medio / ID | Feed configurado / hosts exactos | Campos y evidencia técnica | Acceso y reutilización | Estado H5.7 | Potencial histórico H5.8 |
| --- | --- | --- | --- | --- | --- |
| El Territorio / sin ID H1.1 (el alias `el_territorio` no existe en el catálogo actual) | `https://www.elterritorio.com.ar/rss/misiones`; host H4.8: `www.elterritorio.com.ar` | Título, fecha y enlace observados en cinco fichas de previsualización. Adaptador H4.8 separado de sólo lectura. No pertenece al comando H5.4/H1.1. | La página oficial RSS describe uso de canales en lectores/apps. Eso no determina por sí solo almacenamiento en TrendWatch; documentar alcance de título/fecha/enlace y retención antes de persistir. | Adaptador técnicamente disponible; H5.4 lo rechaza porque no tiene ID H1.1. Requiere integración específica revisada. | Sólo se comprobó el feed actual; no hay evidencia de archivo RSS histórico. El scraper legacy es otro circuito y queda fuera. |
| Noticias del 6 / `noticias_del_6` | `https://noticiasdel6.com/feed/`; hosts: `noticiasdel6.com`, `www.noticiasdel6.com` | H4.2-D: 10 entradas. Se observaron títulos, links y fechas interpretables; 2/2 extracciones con cuerpo suficiente. H4.8: cinco metadatos reales en vista local. Una pasada técnica. | H4.8-G consideró viable la consulta local limitada del feed; ello no constituye licencia general de almacenamiento/republicación. La revisión técnica está registrada; no hay autorización expresa del titular verificada. | Mejor candidato técnico para un piloto de un ítem; todavía requiere una decisión operativa documentada para el uso concreto. | El feed observado sólo prueba el lote vigente (10 entradas); archivo o paginación histórica no verificados. |
| Norte Misionero / `norte_misionero` | `https://nortemisionero.com.ar/feed/`; hosts: `nortemisionero.com.ar`, `www.nortemisionero.com.ar` | H4.2-D: 20 entradas. Se observaron títulos, links y fechas interpretables; 2/2 cuerpos suficientes. H4.8: cinco metadatos reales. | Revisión preliminar de acceso y prueba local limitada registradas; no se acredita permiso de persistir/exhibir indefinidamente metadatos en el producto. Confirmarlo por separado. | Técnicamente listo; autorización de persistencia/exhibición pendiente. | No se comprobó archivo RSS ni recuperación histórica; sólo snapshot del feed. |
| Eldorado Noticias / `eldorado_noticias` | `https://eldoradonoticias.com.ar/feed/`; hosts: `eldoradonoticias.com.ar`, `www.eldoradonoticias.com.ar` | H4.2-D: 10 entradas. Se observaron títulos, links y fechas interpretables; 2/2 cuerpos suficientes. No se consultó en H4.8 por bloqueo de revisión. | `robots.txt` incluye `Crawl-delay: 60`, `Request-rate` y `Visit-time: 0300-1200`; zona horaria de `Visit-time` no verificada y H2.1 sigue redirecciones sólo dentro de hosts permitidos. No hacer GET hasta resolver horario y confirmar que un redirect es aceptable. Reutilización de metadatos también por revisar. | Bloqueado por horario efectivo/UTC local desconocido; acceso y reutilización pendientes. | Feed observado una vez en H4.2-D, pero archivado/paginación no investigados; no estimar historia. |
| Fracrán Noticias / `fracran_noticias` | `https://www.fracran.com.ar/feed.xml`; hosts: `fracran.com.ar`, `www.fracran.com.ar` | H4.2-D: 30 entradas. Se observaron títulos, links y fechas interpretables; 2/2 cuerpos suficientes. | Condiciones públicas reportadas con restricciones para ciertos usos y reproducción; el alcance de consulta automatizada y exhibición persistente de títulos/enlaces no está aclarado. No inferir permiso desde la disponibilidad RSS. | Requiere aclaración de los términos aplicables al uso exacto; no habilitar ni consultar de nuevo mientras siga pendiente. | Sólo lote actual observado; no se comprobó archivo ni capacidad de histórico. |

**Decisión de seguridad actual:** ninguna fuente está en las listas de
habilitación/revisión/aprobación operativa ni en el registro documental de
permiso expreso; ningún intervalo ni límite por fuente está configurado. No se
puede hacer petición ni persistencia con este comando. Noticias del 6 sigue sin
aprobación operativa para el uso concreto y sin permiso expreso verificado. Las
fuentes del catálogo H1.1 permanecen con `habilitada=False`.

## Procedimiento futuro y comprobación

1. Registrar evidencia vigente de acceso automatizado, frecuencia, redirecciones
   y el uso permitido de cada campo a almacenar/exhibir. Si una condición es
   ambigua, dejar el ID fuera de las listas.
2. Configurar sólo el ID elegido en habilitación, revisión y aprobación
   operativa del equipo; fijar límite `1` e intervalo no menor al publicado.
   Registrar permiso expreso del titular sólo si existe evidencia. No cambiar
   el catálogo ni autorizar otros medios.
3. Revisar `python manage.py ingestar_rss_metadatos --help`; luego, con
   PostgreSQL aislado primero, ejecutar una consulta explícita de un ítem y
   confirmar `--confirmar-persistencia`. No usar `ingestar_multifuente`.
4. Comparar el resumen JSON (`nuevas`, `duplicadas`, `rechazadas`, `errores`),
   comprobar una ficha `contenido_completo=False`, cuerpo vacío, fecha RSS o
   NULL, título/fuente/enlace y alias únicos. Verificar que no haya reserva IA,
   análisis, etiquetas ni solicitudes al HTML del artículo.
5. Volver a ejecutar antes del intervalo: debe resultar `BLOQUEADA` sin GET.
   Si hay una interrupción o un fallo de base al guardar el resultado, conservar
   `EN_CURSO` y seguir el procedimiento explícito de revisión; no borrar ni
   editar el control manualmente. Para `Retry-After` mayor a 365 días, dejar la
   fuente en revisión manual hasta confirmar el plazo y acceso. Confirmar
   portada, búsqueda y detalle por el enlace original.

H5.8 no debe reconstruir historia desde feeds actuales. Antes de cualquier
retrospectiva se necesita evidencia de endpoints/archivos históricos, límites y
autorización específica; en su defecto se limita a metadatos aún presentes en
un RSS consultado en adelante. No se propone un valor de fecha histórica ni se
descargan artículos para completar la ficha.
