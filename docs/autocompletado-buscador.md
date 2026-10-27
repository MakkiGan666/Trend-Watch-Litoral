# Autocompletado del buscador — 27/10/2026

Entrega revisada localmente. La sección «Validación y cierre en el proyecto» al final
contiene los resultados vigentes; la validación del paquete se conserva como histórica.

## Base y estado

Implementación local, sin commit, push ni PR. Rama `feat/autocompletado-buscador`, basada en `0c49c68be3f8a50572d3cf37349aaf5cf6c881a0` (PR #29). En la consulta remota el PR #29 sigue abierto y no fusionado. Main está en `ca534d2deddadee0e692db14b5ab3d9fe8a877fb`; ambas ramas han divergido. No se hizo merge ni rebase. El futuro PR deberá apuntar inicialmente a `feat/buscador-noticias` mientras el #29 siga sin integrar.

## Implementación

GET `/api/publicaciones/sugerencias/?q=Mi`, público y sólo lectura. Reutiliza validación, normalización V1 y QuerySet del buscador existente. 2 consultas SQL por entrada válida, sin COUNT de total ni paginación; la frecuencia de términos sí usa COUNT(DISTINCT id). Hasta 5 términos y 4 noticias. HTTP 400 para q ausente, menor de 2 caracteres, inválido o excesivo; 405 para otros métodos; Cache-Control no-store.

Ejemplo de estructura: `{"consulta":"Mi","terminos":[{"texto":"Misiones","consulta":"Misiones"}],"noticias":[{"titulo":"Misiones...","url":"/noticia/1/"}]}`.

Los términos se extraen exclusivamente de títulos reales: tokenización SQL Unicode, agrupación por normalización V1, frecuencia de documentos distintos (repetir una palabra en un título no suma documentos), actualidad y término normalizado como desempates. Se conserva una grafía original mediante MIN. No hay listas fijas, diccionario ni precálculo desactualizable. No se usan los contenidos para generar términos: se privilegia calidad y costo de títulos cortos; los contenidos sí participan en noticias relacionadas.

Para varias palabras se completa la última, manteniendo las anteriores como contexto y exigiéndolas en la publicación. Seleccionar un término envía esa consulta completa al formulario tradicional. Las noticias exigen todos los términos y priorizan cuántos coinciden en título, luego fecha efectiva y PK. Coincidencias parciales iguales a la búsqueda anterior.

PostgreSQL tokeniza con regexp_split_to_table, usando un patrón constante, y normaliza NFC antes de comparar. El SQL incluye únicamente SQL compilado por Django y constantes, entradas parametrizadas y escape explícito para LIKE. SQLite usa json_each y una función determinista por conexión sólo para compatibilidad; no se cambió la función versionada ni las columnas generadas.

## Visibilidad

En este HEAD Publicacion no tiene campos de publicación/ocultación/borrador: el buscador actual expone todas las Publicacion. Se conserva ese contrato. No se agregaron ni inventaron estados. Si se incorporan estados en otra rama, centralizar el QuerySet público y aplicar idéntico filtro al origen de términos y a noticias antes de integrar. Por ausencia de esos estados, no se simula una prueba de borradores inexistentes. Las noticias sin categoría/departamento/IA siguen siendo consultables.

## Frontend

Fragmento compartido con endpoint resuelto por Django; cada campo tiene control independiente. Debounce 300 ms, mínimo 2 caracteres, límites de longitud, AbortController y número de versión; timeout de red 5 s. No se consulta durante composición IME. Cerrar, borrar, plegar la barra, perder foco o enviar invalida la petición. Una respuesta antigua no puede repintar el listado.

Dos grupos en listbox, combobox con aria-controls/expanded/autocomplete/activedescendant, opciones con aria-selected y anuncio discreto. Flechas recorren, Enter activo selecciona, Enter sin selección conserva formulario, Escape cierra primero sugerencias y luego permite cerrar la barra. En el paquete original pointerdown seleccionaba inmediatamente; el cierre documentado abajo corrige el desplazamiento táctil. Término envía formulario GET, noticia navega a detalle interno del mismo origen; protocolos y ruta se validan. Se usa textContent, nunca HTML de la base.

Sin JS no se agrega el panel y sigue funcionando el formulario original. Desplegable en flujo normal con altura máxima y scroll, estilos del sitio. No se modificaron schema, permisos, ingesta, comentarios ni valoraciones. Se actualizaron versiones de assets en base e Inicio.

## Validación histórica del paquete (antes de esta revisión)

Entorno de esta revisión: Python 3.12.14, Django 5.2.18 (no la versión fijada 6.1.2 del proyecto), SQLite. No se alteró requirements.txt. El entorno no tiene Docker ni servidor PostgreSQL instalados.

- 56 tests Django aprobados: `core.test_sugerencias core.test_buscador core.test_busqueda_html core.test_comentarios core.test_valoraciones core.test_navegacion_admin`; 1,596 s. Se ejecutan sobre base de test en memoria.
- 4 tests JS con Node 24 y jsdom: mínimo/debounce/cancelación/race; flechas/Enter/Escape; pointerdown/texto seguro/vacío/error HTTP; IME/blur. Aprobados tras el último ajuste JS.
- Consulta PostgreSQL de términos ejecutada de forma complementaria en PostgreSQL 18.6 embebido (PGlite, WASM); prefijos, grafía acentuada, agrupación y frecuencia comprobados. NO equivale a suite Django sobre PostgreSQL 17/PostGIS.
- Sintaxis JS y diff --check correctos.
- El check de pruebas mostró 8 advertencias W042 de PK preexistentes; no se modificaron PK para ocultarlas.

Para pruebas JS, jsdom se usó como herramienta temporal de desarrollo, no dependencia del producto. Instalar en directorio temporal con `npm install --prefix /tmp/tw-autocomplete-tests jsdom` y ejecutar `NODE_PATH=/tmp/tw-autocomplete-tests/node_modules node --test tools/buscador/test_autocompletado.cjs`.

## Pendientes originales del paquete (estado histórico)

1. Suite focalizada en Docker PostgreSQL/PostGIS con dependencias fijadas; no usar la base real. Comprobar 2 SQL, prefijos Unicode, términos literales, ranking y regresiones.
2. Medir endpoint con 500 y 5.000 noticias sintéticas: la extracción SQL aún recorre títulos; no se afirma rendimiento de producción sin medición.
3. Revisión real en navegador de layout, teclado nativo, foco, toque, red caída y sin JS. DOM simulado no sustituye revisión visual, lector de pantalla ni móvil físico.
4. Confirmar nuevamente el HEAD de PR29/main al aplicar; no resolver conflictos a ciegas.
5. Guardar en commit local y publicar únicamente con autorización posterior. No aplicar cambios de esquema: esta etapa no agrega migraciones.

## Validación y cierre en el proyecto

### Preparación y base comprobada

Se leyeron AGENTS.md, LEEME, documentación y patch completos antes de modificar.
`git fetch origin` confirmó PR #29 abierto/en borrador, no fusionado, HEAD
`0c49c68be3f8a50572d3cf37349aaf5cf6c881a0`; origin/main está en
`ca534d2deddadee0e692db14b5ab3d9fe8a877fb` tras PR #30, y no contiene todavía el buscador.
No se tomó main como base ni se incorporó su trabajo de ingesta. Se creó
`feat/autocompletado-buscador` en el worktree hermano `trendwatch-autocompletado`.
`git apply --check` pasó y luego se aplicó el paquete. No hubo conflictos que adaptar.
Los archivos locales de los otros worktrees y el paquete original se conservaron.
Sin commit, push, PR, merge, rebase ni reset.

### Hallazgos y correcciones

- **Contexto repetido:** se completaba `terminos[-1]` después de deduplicar, que no
  necesariamente era la última palabra escrita. Ahora se obtiene el prefijo de la
  consulta normalizada sin deduplicar y se deduplica sólo el contexto anterior.
- **Alcance público:** origen de términos y noticias usan siempre
  `publicaciones_coincidentes`, incluso con contexto vacío. Hoy equivale a todas las
  Publicacion; ni el HEAD base ni origin/main tienen estados de borrador/ocultación.
  Una prueba restringe el helper deliberadamente y verifica que ambos caminos lo
  respetan. No se inventan permisos ni estados. Sin categoría/departamento/IA se
  participa igualmente, tanto por título como por contenido.
- **Títulos frente a contenido:** se conserva la decisión de producto del paquete:
  términos sólo desde títulos; noticias desde título O contenido. Una coincidencia
  exclusiva del contenido puede devolver noticias con `terminos: []`. Es diferencia
  de vocabulario sugerido, no de visibilidad de publicaciones.
- **Consultas seleccionables:** se limita en SQL la longitud original de la palabra
  según el espacio restante hasta 150 caracteres, antes de LIMIT. No se sugieren
  palabras de un carácter que al plegarse se expanden a dos (`İ`), ni términos que
  produzcan consultas demasiado largas. Los límites no se truncan.
- **Toque y scroll:** seleccionar al pointerdown impedía distinguir un toque de un
  arrastre. Mouse conserva foco y selecciona en click; touch selecciona en pointerup
  sólo si no hubo desplazamiento >10 px/cancelación. Un arrastre no navega.
- La longitud en cliente cuenta puntos de código, como Python; el servidor sigue
  siendo la autoridad. Cache-Control no-store cubre también GET inválido. No se
  ocultan errores internos como sugerencias vacías.

No se modificaron el buscador previo, normalización V1, modelos, migraciones,
clasificación, ingesta, scrapers ni procesamiento IA. Nuevos archivos funcionales:
`core/services/sugerencias.py`, `core/test_sugerencias.py`; integración en vista/ruta,
fragmento de formulario y CSS/JS news-search, con versiones de assets en base/Inicio.
Las herramientas nuevas y capturas están dentro de `tools/buscador` y
`docs/capturas/autocompletado`. Evidencia compacta: `autocompletado-resultados.json`.

### Pruebas vigentes y reproducción

Con Docker, Bash, Python 3 y la imagen local construida a partir de requirements:

```bash
docker build -t trendwatch-litoral-web:latest .
bash tools/buscador/validar_autocompletado.sh postgresql
bash tools/buscador/validar_autocompletado.sh sqlite
bash tools/buscador/validar_autocompletado.sh medir
```

El launcher usa PostgreSQL/PostGIS propio con network none, sin puertos ni volúmenes
persistentes; verifica una marca de su base antes de migrar o medir y limpia sólo
su contenedor etiquetado. SQLite vive en tmpfs. No acepta DSN o bases existentes,
ignora dotenv y genera un secreto temporal. No se modificó requirements.

Etiquetas exactas, **sin ejecutar la suite completa**:
`core.test_sugerencias core.test_buscador core.test_busqueda_html core.test_texto_busqueda
core.test_fechas core.test_comentarios core.test_valoraciones core.test_navegacion_admin`.

| Motor | Ejecución final | Tiempo |
|---|---|---:|
| PostgreSQL 17.5/PostGIS | 85 tests, OK, 1 omitido exclusivo del registro SQLite | 4.077 s |
| SQLite real | 85 tests, OK, sin omisiones | 3.226 s |

Las 15 pruebas de sugerencias están incluidas en esos 85. Comprueban prefijos,
frecuencia por documento, límites, Unicode NFC/NFD/tildes/diéresis/ñ, contexto
repetido, literales `%`, `_` y barra inversa, ranking y desempate, acceso anónimo,
actualización/borrado, 2 consultas de lectura sin HTTP externo, errores internos,
formato y alcance compartido. Se ejecutaron primero 82 casos y luego se añadieron
los tres casos finales de escape/ranking/equivalencia: no sumar ambas ejecuciones.
Django check 0 incidencias y migraciones desde cero sin pendientes en ambos motores.
No se generaron migraciones; el desfase global de cuatro IDs del buscador anterior
sigue fuera de alcance y no se intentó arreglarlo.

Cinco pruebas DOM con Node 20.19.2 y jsdom 26.1.0, todas aprobadas (0 omisiones):
las cuatro del paquete y toque/arrastre/cancelación. Instalación sólo temporal:

```bash
npm install --prefix /tmp/tw-autocomplete-devtests jsdom@26.1.0
NODE_PATH=/tmp/tw-autocomplete-devtests/node_modules node --test tools/buscador/test_autocompletado.cjs
```

No es dependencia del producto. Sintaxis Python/JS/bash y `git diff --check` correctos.

### Rendimiento del endpoint

Una sola batería secuencial, sin otras suites/mediciones propias concurrentes.
Corpus reproducible del buscador anterior: 500 y 5.000 títulos `Educación provincial N`,
contenido de 2.040 caracteres base y marca singularis cada 499 noticias, fechas fijas,
sin clasificación/IA. Se mide el recorrido completo con cliente Django, JSON y URLs,
no HTTP de red ni navegador. Se hacen 6 peticiones por caso: se descarta la primera y
se informa mediana de 5. Dos tiempos SQL se miden por separado con execute_wrapper;
no sumar medianas como si fueran una misma ejecución. Son siempre **2 consultas**,
sin total/paginación y con respuestas idénticas entre repeticiones.

| Filas | q | Endpoint ms | SQL términos ms | SQL noticias ms | Términos/noticias |
|---:|---|---:|---:|---:|---:|
| 500 | ed | 8.576 | 4.923 | 0.854 | 1/4 |
| 500 | singularis | 9.599 | 4.274 | 1.815 | 0/2 |
| 500 | inexistentezz | 9.600 | 4.571 | 2.417 | 0/0 |
| 500 | educacion pro | 10.503 | 6.063 | 0.887 | 1/4 |
| 5000 | ed | 65.851 | 59.949 | 3.564 | 1/4 |
| 5000 | singularis | 68.238 | 49.947 | 14.617 | 0/4 |
| 5000 | inexistentezz | 76.900 | 51.671 | 22.772 | 0/0 |
| 5000 | educacion pro | 76.035 | 67.582 | 4.703 | 1/4 |

Entorno: PostgreSQL 17.5, UTF8, collation/ctype en_US.utf8, PostGIS imagen 17-3.5,
Django 6.1.2 y Python 3.13.16 (versiones fijadas), Linux x86_64/Docker, datos tmpfs.
Se ejecutó ANALYZE después de cargar cada tamaño. Los tiempos no incluyen migrar ni
crear corpus. Los inserts se revirtieron y el contenedor/base se eliminaron.

El costo principal observado es extraer/normalizar/agrupar palabras de títulos
(aprox. 50–68 ms a 5.000); no se normaliza contenido por petición. El crecimiento
es coherente con recorrer los títulos, sin regresión superlineal inesperada en esta
muestra. La mediana completa a 5.000 es 65,851–76,900 ms, **más** debounce 300 ms y
latencia de red en la experiencia real. No se agregaron índices ni variantes nuevas.
Es suficiente para continuar con auditoría funcional al volumen ensayado; no demuestra
capacidad concurrente ni p95. Corpus repetitivo/cacheado y host compartido: no
extrapolar a títulos largos/reales, otros idiomas/collations o volúmenes mayores.
No se reabrió la investigación de normalización persistida ya concluida.

### Navegador y capturas

```bash
bash tools/buscador/previsualizar_busqueda.sh iniciar
# Usar el origen sin ruta de la URL generada en ese equipo:
python3 tools/buscador/revisar_autocompletado.py ORIGEN_GENERADO docs/capturas/autocompletado
bash tools/buscador/previsualizar_busqueda.sh detener RUTA_DEL_MANIFIESTO
```

Firefox 145.0.1, BiDi con Node 20 WebSocket nativo, perfiles separados y efímeros.
**15 comprobaciones con JS y 2 sin JS**, todas conformes. En esta revisión sí
funcionó el teclado nativo: se usó Return E006 (no el Enter de teclado numérico E007
usado por el controlador previo). Se confirmó entrada/teclas trusted, flechas,
aria-activedescendant, Enter seleccionado y Enter sin seleccionar que envía GET,
Escape/foco y dos Escape para plegar barra. Clic mouse y puntero touch nativos:
toque selecciona, arrastre no navega. Se interceptó/falló la red de sugerencias y
el formulario tradicional siguió funcionando. También vacío, panel limitado,
no desbordes y ausencia de panel con JavaScript realmente deshabilitado.

Capturas revisadas:
[escritorio 1440×1000](capturas/autocompletado/sugerencias-1440.png),
[móvil 390×844](capturas/autocompletado/sugerencias-390.png),
sin JS 390×844 (captura conservada localmente; se incluyen sólo las dos capturas representativas anteriores).
Los JSON `revision.json` y `revision-sin-js.json` conservan cada comprobación.
Se bloquearon fuentes/destinos externos: tipografía alternativa local. Puntero touch
es emulado, no un móvil físico. **Pendientes:** lector de pantalla, móvil físico,
Safari/Chromium y auditoría final antes de integrar. La limitación previa de foco
inicial del modal de cuenta no fue alterada.

### Estado al cerrar la validación previa (histórico)

Patch original y otros worktrees preservados. No hay migraciones nuevas, commit,
push ni PR. El HEAD de esta rama sigue siendo 0c49c68. Si #29 aún no se integra,
el futuro trabajo se compara contra feat/buscador-noticias; volver a verificar el
remoto antes de publicar. Se retiraron los contenedores/red de prueba y los perfiles
Firefox propios. Herramienta jsdom y logs compactos quedan en /tmp; no se guardan
secretos, bases, dumps ni perfiles en el repositorio.

### Prueba manual del usuario y commit local

El 27/10/2026 el usuario informó que probó manualmente la previsualización y que
el autocompletado funciona correctamente. Se registra ese resultado satisfactorio
sin atribuirle escenarios, dispositivos o comprobaciones específicas no informadas.
Los pendientes de accesibilidad y otros navegadores no se dan por resueltos por
esa declaración general.

Por autorización expresa, la funcionalidad, sus pruebas, herramientas reproducibles,
evidencias compactas y dos capturas representativas se guardan en un commit local
separado sobre 0c49c68. No se modificó código ejecutable durante esta preparación:
se reutilizan las 85 pruebas por motor, cinco de DOM y 15+2 de navegador ya descritas.
Se verifica git diff --cached --check antes del commit. Sin push, merge ni PR nuevo.
La previsualización sintética iniciada para el usuario permanece activa; sus datos,
manifesto y recursos temporales no se incorporan al repositorio. Los otros worktrees
se preservan. La captura sin JavaScript se excluye del commit, sin eliminarla.
