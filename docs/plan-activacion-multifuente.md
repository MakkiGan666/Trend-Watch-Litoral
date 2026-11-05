# H4.2-A — Plan previo de activación multifuente

Fecha: 2026-11-05. Base revisada: `64e3e18fef6b34e766fecc6e460a68645e3ccac1`.
Rama: `feat/h4-2-validacion-fuentes`. **No habilitar todavía ninguna fuente.**

## Alcance y evidencia

Revisión estática de catálogo H1.1, transporte H2.1, lector H2.2, extractor H2.3,
persistencia H3.1, Gemini H3.2, orquestador y comando H4.1, modelos, señales y
migraciones. No hubo HTTP, consultas a bases existentes, migraciones ni ingestas.
Se conserva la evidencia previa de 40 pruebas del orquestador y 29 de persistencia
aprobadas en SQLite, cuatro verificaciones puntuales PostgreSQL, Django check y
controles de diff. No se repitieron suites. La integración de las 18 fuentes usa
feeds y HTML simulados: no demuestra disponibilidad ni calidad editorial real.

## Bloqueos antes de producción

- [ ] **Validación por medio pendiente:** no se verificaron ahora DNS, TLS, redirects,
  disponibilidad de los feeds, HTML actual, imágenes ni condiciones de uso.
  El comentario del catálogo sobre la auditoría H1.1 no sustituye evidencia actual.
  Requiere una etapa separada autorizada de captura sin persistencia y fixtures
  representativos; no habilitar en bloque a partir de las pruebas simuladas.
- [ ] **Esquema y recuperación sin certificar en destino:** confirmar 0019, ensayar
  0020/0021 y restauración sobre una copia aislada antes de autorizar la ventana.
  H4.1 aborta por esquema incompatible incluso en dry-run. El procesador global
  usa estas tablas sin el preflight H4.1: no arrancarlo sobre un esquema anterior.
- [ ] **Control de IA entre procesos:** `--sin-ia` evita Gemini en esa ejecución,
  pero H3.1 crea pendientes que `GeminiCliente.procesar_pendientes` puede consumir.
  `run_pipeline` también invoca ese procesador. Identificar y coordinar todos los
  disparadores antes del piloto; si no pueden aislarse sin afectar El Territorio,
  hace falta un control separado de consumo IA multifuente antes de activar.
- [ ] **Operación de pendientes e incidentes:** asignar responsable y procedimiento
  para `ERROR`, `INCIERTO` y `EN_PROCESO` con envío marcado. No hay comando específico
  de conciliación; la función `procesar_pendientes_multifuente` permite recuperar
  pendientes sin recibo, pero su ejecución operativa necesita autorización aparte.
- [ ] **PostgreSQL:** verificar Read Committed en las conexiones reales de los workers,
  permisos y capacidad. H3.1 rechaza otro aislamiento al guardar; el preflight físico
  no lo detecta antes de HTTP y puede quedar un RegistroDatos de ejecución fallida.

No se identificó un nuevo defecto bloqueante de las dos correcciones finales de
H4.1. Los puntos anteriores son condiciones de habilitación todavía no acreditadas.

## Catálogo y cambios por fuente

Las 18 fuentes tienen `habilitada=False`, 30 entradas como tope de catálogo,
10 segundos por descarga, 1.500.000 bytes y cuatro redirects. Hay 36 hosts exactos
sin solapamientos: para cada dominio de la tabla sólo se admite su apex y `www`.
No hay comodines, IP literales, puertos alternativos ni hosts de otros medios.
HTTPS y DNS público se verifican en cada salto; la conexión fija la IP validada
con SNI/TLS del host original. No se descargan imágenes, scripts ni contextos JSON-LD.

El orden siguiente es **provisional**, por formato de URL/feed y diversificación
territorial, no un ranking de fiabilidad. Todos los pasos tienen la misma puerta
de aceptación. Alterarlo si las muestras indican menor riesgo en otra fuente.

| Orden | ID | Feed configurado | Cambio individual posterior a la aprobación |
| ---: | --- | --- | --- |
| 1 | `misiones_online` | `https://misionesonline.net/feed/` | Sólo `habilitada=True` en su entrada |
| 2 | `primera_edicion` | `https://www.primeraedicion.com.ar/feed/` | Sólo `habilitada=True` en su entrada |
| 3 | `noticias_de_la_calle` | `https://www.noticiasdelacalle.com.ar/rss/noticias` | Sólo `habilitada=True` en su entrada |
| 4 | `noticias_del_6` | `https://noticiasdel6.com/feed/` | Sólo `habilitada=True` en su entrada |
| 5 | `infober` | `https://infoberdigital.com/feed/` | Sólo `habilitada=True` en su entrada |
| 6 | `obera_online` | `https://oberaonline.com.ar/feed/` | Sólo `habilitada=True` en su entrada |
| 7 | `obera_inside` | `https://oberainside.com.ar/?feed=rss2` | Sólo `habilitada=True` en su entrada |
| 8 | `stop_en_linea` | `https://www.stopenlinea.com.ar/rss/noticias` | Sólo `habilitada=True` en su entrada |
| 9 | `e24n` | `https://e24n.com.ar/feed/` | Sólo `habilitada=True` en su entrada |
| 10 | `eldorado_noticias` | `https://eldoradonoticias.com.ar/feed/` | Sólo `habilitada=True` en su entrada |
| 11 | `norte_misionero` | `https://nortemisionero.com.ar/feed/` | Sólo `habilitada=True` en su entrada |
| 12 | `la_voz_de_cataratas` | `https://lavozdecataratas.com/feed/` | Sólo `habilitada=True` en su entrada |
| 13 | `iguazu_ahora` | `https://iguazuahora.com/feed/` | Sólo `habilitada=True` en su entrada |
| 14 | `radio_yguazu` | `https://radioiguazu.com/feed/` | Sólo `habilitada=True` en su entrada |
| 15 | `alem_news` | `https://www.alem.news/feed/` | Sólo `habilitada=True` en su entrada |
| 16 | `la_mision_digital` | `https://lamisiondigital.com/feed/` | Sólo `habilitada=True` en su entrada |
| 17 | `fracran_noticias` | `https://www.fracran.com.ar/feed.xml` | Sólo `habilitada=True` en su entrada |
| 18 | `noticias_de_irigoyen` | `https://noticiasdeirigoyen.com.ar/feed/` | Sólo `habilitada=True` en su entrada |

El cambio mínimo futuro está en `app/core/services/fuentes_rss.py`; no en el comando,
la base ni 18 scrapers. Mantener ID y nombre estables: intervienen en identidad,
consulta de históricos y elegibilidad IA. Reiniciar los procesos tras un cambio
aprobado para evitar catálogos importados distintos. Si una muestra requiere otro
feed, host de imágenes/CDN, charset o estructura, revisar por separado su propiedad,
política y fixture antes de cambiarlo. No ampliar hosts para sortear un rechazo.
Imágenes de CDN externo se omiten por diseño; no constituyen un fallo SSRF.

## Procedimiento de migraciones (propuesto; no ejecutado)

1. **Preparar y aprobar:** inventariar versión de aplicación y esquema, escritores,
   jobs y procesadores globales; confirmar backend PostgreSQL y 0019 aplicada.
   Revisar el plan para que sólo 0020 y 0021 estén pendientes; si hay otras
   dependencias pendientes o tablas preexistentes divergentes, detenerse. No usar
   `--fake`. Verificar credenciales por el mecanismo habitual sin volcarlas en logs.
2. **Backup:** establecer ventana y pausar escritores/consumidores de forma coordinada,
   incluida la ingesta habitual si comparte la base. Conservar backup consistente
   PostgreSQL completo (datos, esquema, registro de migraciones) y roles/permisos
   necesarios para restaurar; incluir media si corresponde. Cifrar, restringir acceso,
   registrar checksum, versión, hora y responsables. Definir RPO/RTO y probar la
   restauración en otra instancia aislada, nunca sobrescribir el origen para probar.
3. **Ensayo aislado:** restaurar la copia, ejecutar allí `showmigrations core`,
   `migrate core 0021 --plan`, revisar `sqlmigrate core 0020` y `sqlmigrate core 0021`.
   Aplicar sólo el plan aprobado. Cotejar modelos/migraciones y probar el preflight
   directamente, sin descarga; ejecutar pruebas con HTTP/Gemini simulados.
   Confirmar Read Committed, unicidad, FK, nulabilidad, tipos, tamaños y auto-ID.
4. **Ventana futura, con autorización explícita:** respaldar de nuevo y aplicar
   el plan ensayado con rol de migración, antes de arrancar código que consulte
   la cola. Poner tiempos máximos de bloqueo/ejecución y detener ante contención.
   El rol de ejecución no necesita permiso para modificar esquema. El plan H4.2-A
   no autoriza ejecutar estos pasos en destino.
5. **Verificar:** 0020 depende de 0019 y sólo crea alias con FK y UNIQUE
   `(fuente, url_normalizada)`; 0021 depende de 0020 y sólo crea cola con PK/FK a
   Publicacion. No hay RunPython, backfill, fusiones ni rehash. Las tablas nuevas
   deben estar vacías antes del piloto. Comparar conteos, IDs y hashes históricos
   con la instantánea previa; ejecutar preflight y Django check. Reanudar únicamente
   los procesos autorizados, manteniendo todas las fuentes deshabilitadas.
6. **Rollback operativo preferido:** detener nuevas ejecuciones, deshabilitar sólo
   la fuente piloto mediante cambio revisado y conservar las tablas y lo ya guardado.
   Volver a una versión compatible con el esquema; H3.2 ya requiere 0020/0021.
   No borrar publicaciones para deshacer una activación ni perder su cola/alias.
7. **Rollback de esquema, excepcional:** ensayar en copia `migrate core 0019 --plan`.
   La reversión Django elimina primero 0021 y luego 0020: es técnicamente reversible
   pero **destruye pendientes, recibos de envío y alias**, aunque conserve Publicacion.
   Sólo considerar con respaldo/exportación y autorización expresa, sin consumidores
   activos. Reaplicar después no reconstruye esas identidades ni permite saber qué
   llamadas fueron enviadas. Si hubo actividad, preferir corrección hacia adelante;
   restauración total exige conciliar escrituras posteriores y resultados externos
   para no perder datos ni repetir llamadas a Gemini.

## Activación gradual futura

- [ ] Fase 0: resolver los bloqueos anteriores, ensayar esquema y recuperar backup;
  guardar fixtures reales autorizados sin datos sensibles. Sin fuentes habilitadas.
- [ ] Fase 1: habilitar únicamente `misiones_online` mediante cambio revisado.
  Primero un dry-run con `--fuente misiones_online --limite-fuente 1 --limite-total 1
  --dry-run --sin-ia`. Dry-run sí usa HTTP; queda fuera de esta preparación.
  Un presupuesto de uno puede impedir recuperar otra canónica: revisar `limitada`.
- [ ] Fase 2: una ejecución autorizada con los mismos límites y `--sin-ia`.
  Verificar publicación, alias, categorías, etiquetas y pendiente IA; repetir para
  confirmar cero altas y mismos IDs/hashes. No ejecutar `run_pipeline` para este piloto.
- [ ] Fase 3: revisar manualmente al menos 20 artículos distintos por medio a lo largo
  de varias ejecuciones de 1–3 entradas; avanzar sólo tras dos jornadas sin incidentes.
  Si hace falta recuperación canónica, aumentar explícitamente el presupuesto a dos.
- [ ] Fase 4: autorizar IA para una noticia nueva, con `--con-ia --limite-ia 1` y cupo
  de ejecución acotado; controlar también el procesador global. No usar un histórico
  como prueba. Revisar resultado y coste antes de ampliar hasta cinco llamadas.
- [ ] Fase 5: incorporar una fuente por vez según la tabla; cada una repite las puertas
  anteriores. Mantener las demás deshabilitadas hasta aprobarlas; no programar las
  18 juntas ni escalar por un único resumen `EXITO`.

## Criterios de aceptación por medio

Umbrales propuestos para aprobar, no métricas observadas. Registrar muestra,
fecha, versión, denominadores y causas de rechazo; una fuente vacía no aprueba.

| Aspecto | Criterio verificable |
| --- | --- |
| Seguridad | Cero hosts ajenos aceptados, cero SSRF/redirects cruzados; cero HTTP extra de parsers o imágenes. No relajar límites para aprobar. |
| Títulos | 100% de los aceptados no vacíos, ≤255 caracteres, sin truncamiento ni controles; ≥95% coinciden con el titular editorial, conservando texto literal. |
| Fechas | 100% presentes válidas y con zona; ninguna inventada. Si faltan en ambos orígenes, conservar None y medir faltantes; ≥95% de la muestra con fecha verificable para avanzar. |
| Cuerpo | ≥95% de la muestra produce contenido persistible que representa el artículo; 100% de aceptados sin NUL/controles, menús, publicidad o párrafos duplicados. No tratar resumen como cuerpo. El mínimo técnico de 120 caracteres/20 palabras no prueba calidad. |
| Imágenes | 100% de URLs guardadas HTTPS y hosts propios; ninguna descarga. Medir cobertura sobre imágenes principales alojadas en hosts permitidos; objetivo ≥90%, documentando omisiones por CDN ajeno sin habilitarlo implícitamente. |
| Identidad | Cero duplicados nuevos en reintentos, orden RSS/canónica inverso y concurrencia con RSS distintas. Misma noticia de dos medios permanece separada. IDs/hashes históricos idénticos. |
| Gemini | Una llamada como máximo por intento enviado; sólo altas H3.1, sin resultados previos. JSON validado, polaridad/confianza en rango y localidades plausibles verificadas manualmente; cero resultados históricos sobrescritos. No hay extracción general de entidades en H3.2: no prometerla. |
| Operación | Sin error de persistencia, conflicto pendiente o envío incierto sin responsable. Revisar por fuente `rechazadas`, `errores`, `limitada`, `persistencia_incierta` y pendientes IA. PARCIAL puede salir sin error de proceso: inspeccionar JSON, no sólo exit code. |

Ante incumplimiento: detener expansión, conservar evidencia y datos, deshabilitar
la fuente con revisión y resolver la causa. No reenviar automáticamente IA incierta.

## Riesgos y controles operativos

- **Históricos:** `_existente` revisa alias, hash y URLs normalizadas dentro del medio;
  múltiples IDs compatibles producen `conflicto_identidad`, sin fusión. Preparar una
  revisión de sólo lectura autorizada por separado y resolver manualmente antes de
  reintentar. No recalcular hashes ni normalizar en masa registros existentes.
- **Escala y bloqueos:** la consulta histórica recorre las URLs de cada medio y H3.1
  serializa escritores por fuente con advisory lock hasta commit/rollback. Medir
  duración con volumen representativo y establecer lock/statement timeout y alerta;
  SQLite no acredita concurrencia PostgreSQL ni sustituye Read Committed.
- **Tiempo y recursos:** presupuestos cuentan entradas admitidas y consultas canónicas
  adicionales; feeds, redirects y esperas IA suman tiempo. El timeout HTTP no acota
  por sí solo `getaddrinfo`; fijar vigilancia/límite externo de ejecución. Un corte
  durante Gemini puede dejar un envío marcado sin resultado: conciliación manual.
- **Cola IA:** PENDIENTE y EN_PROCESO sin envío siguen recuperables. COMPLETADO no se
  reenvía; ERROR/INCIERTO y EN_PROCESO con envío no son reintentos automáticos.
  Registrar IDs, estados, timestamps y códigos, sin cuerpos ni credenciales. Un envío
  marcado puede no haber llegado al proveedor; no hay garantía de exactamente una
  respuesta, ni conciliación automática con el proveedor. Definir alertas y SLA de revisión.
- **Cobertura real:** parser sin JavaScript y sólo charsets admitidos; paywalls, HTML
  distinto, feeds malformados, CDN externo o cambios de red pueden reducir cobertura.
  Rechazar y registrar; ampliar reglas compartidas sólo con fixture y aprobación.

**Salida de esta etapa:** documento de preparación; no constituye aprobación de
producción, migraciones, llamadas externas ni habilitación de ninguna de las 18 fuentes.
