# Fase 2.2 — Compatibilidad de categorías, previa a CAT-02

Base local: b6ad626b9181d8d71d15b3bbe8e3be49f23d18e0,
rama fix/stabilizacion-pr23-fase1-1. Estado inicial limpio.
CAT-01 se leyó con `git show docs/cat-01-especificacion:docs/categorias/CAT-01-especificacion.md`
en 8a0735f15ca1f3afb82e8c60f3842a48992863a1. Es diseño acordado para implementación
posterior, no un contrato ya implementado. PR #24 se inspeccionó por objetos Git
7acc16a7d0ef8fd5d10abe7be9a1594d48936981, sin cambiar otro worktree.

## Comparación de contratos

| Aspecto | CAT-01 | PR #23 / consumidores PR #24 | Resolución de esta fase |
| --- | --- | --- | --- |
| Catálogo | Cuatro iniciales: Salud, Policiales, Turismo, Festividades; ampliable | Doce nombres de la portada/prototipo | Conservar doce y todo registro histórico; no aprobar ampliación ni eliminar categorías unilateralmente |
| Cardinalidad | Múltiples relevantes, sin duplicados | Modelo admite múltiples; clasificador elige una | Lectura múltiple común; no imponer respuesta múltiple sobre el clasificador existente |
| Identidad | ID + codigo único + nombre visible | Categoria sólo tiene ID y nombre | Exponer IDs/nombres reales sin inventar códigos derivados |
| Respuesta clasificadora | Objeto categorias con lista de códigos; [] válido | Arreglo de indice/categoria por lote, nombres cerrados | Conservar parser separado; rechazar claves repetidas y conservar incertidumbre de elementos no resueltos |
| Gemini de sentimiento | No confundir temática con sentimiento | Esquema polaridad/confianza/localidades, sin categorías | No modificar su esquema, validador ni procesado_ia |
| API publicaciones | categorias como objetos y estado_clasificacion | categorias como lista de nombres, con fallback a sección | Conservar campo legacy y añadir detalles/procedencia de lectura |
| Desconocida | Conservar noticia sin coincidencia; distinguir pendiente/error | Fallback Sociedad termina asociado igual que una regla clara | No asociar propuestas no confirmadas; conservar noticia y contar sin_categoria |
| Históricos | Proteger manual/legado y reemplazar sólo asociaciones propias | No existe origen en PublicacionTema | Ninguna reclasificación, borrado o inferencia de origen |
| Temas generales | Tema.es_general con unicidad e inicialización | Asociación mediante primer Tema de la categoría o uno nuevo | Pendiente CAT-02: no convertir un tema específico a general por inferencia |

## Defectos objetivos corregidos

1. `categoria_con_confianza` ya señalaba incertidumbre, pero `clasificar_lote` la
   descartaba. El scraper asociaba Sociedad incluso por ausencia total de evidencia.
2. La sección RSS de fuente aparecía como categoría en el detalle, y API/detalle/panel
   consultaban o representaban las relaciones de maneras diferentes.
3. La portada sólo entendía nombres de categoría; un futuro objeto CAT-01 terminaba
   convertido a texto genérico y no se agrupaba correctamente.
4. El parser temático aceptaba objetos JSON con claves duplicadas y aplicaba la
   última sin rechazar la ambigüedad. El validador de sentimiento ya la rechazaba.

## Cambios compatibles y límites

`clasificar_lote` mantiene categoria/departamento/metodo y añade `confirmada`:
true sólo para reglas que el algoritmo existente considera seguras o una respuesta
IA validada. Es una decisión operativa del algoritmo, no certeza editorial.
El campo categoria conserva la propuesta legacy, incluido Sociedad si no hay
indicios; `categoria_por_reglas` mantiene su retorno por compatibilidad y no debe
usarse solo como autorización para persistir.

El scraper requiere `confirmada is True` antes de asociar. Si falta el indicador
o es falso, guarda la publicación sin vínculo automático. No la descarta ni cambia
los cinco estados de ingesta. `categorias` del resumen cuenta únicamente asociaciones
creadas para las altas; `sin_categoria` cuenta altas sin asociación y se conserva
ante fallos posteriores. Incertidumbre temática no significa cobertura fallida de
la fuente. Los duplicados no se vuelven a clasificar ni se alteran.

Sin IA, las propuestas dudosas de cualquier categoría quedan sin asociación,
no sólo las de Sociedad. Una sección específica o palabras claras de Sociedad
pueden seguir confirmándola. Una IA ausente, fallida o con respuesta parcial no
confirma las propuestas que no resolvió. El protocolo de clasificación sigue
siendo separado del de sentimiento; no se añadió ninguna llamada real a Gemini.

`core/categorias.py` lee todos los temas, deduplica categorías por ID y ordena por
ID para una representación estable. Conserva categorías ajenas a las doce y IDs
distintos con el mismo nombre. La lista legacy de nombres deduplica esos nombres.
No normaliza, fusiona ni borra registros. Las listas de categorías no tienen una
prioridad temática; su orden previo dependía del recorrido de las relaciones.

Los listados global/local y detalle API mantienen los campos actuales y añaden:

- `categorias_detalle`: asociaciones reales como objetos `{id, nombre}`. No es
  todavía la representación completa de CAT-01: deliberadamente no incluye codigo.
- `categorias_origen`: asociaciones / seccion / sin_datos. Es procedencia de la
  **lectura**, nunca origen manual/automático/legado ni estado de clasificación.
- `seccion_origen`: texto entre paréntesis en fuente o null, sin validar como catálogo.

El campo legacy `categorias` conserva su tipo lista de nombres y el fallback de
sección. Los consumidores nuevos deben preferir categorias_detalle: una lista vacía
es autoritativa y no habilita inferir categoría desde la fuente. El detalle HTML
identifica separadamente la sección. El panel muestra todas las categorías asociadas
y sus IDs, con prefetch para evitar consultas por categoría.

La portada sigue admitiendo nombres legacy y ahora acepta objetos con nombre o
codigo. Conserva múltiples categorías, elimina duplicados y no usa la fuente si
recibe una lista autoritativa vacía. Sólo agrupa claves con sección visible; una
categoría histórica ajena al catálogo se conserva en API/detalle/panel, pero no se
mapea a Sociedad para forzar una tarjeta. Noticias sin categoría continúan almacenadas
y accesibles por API/panel/detalle; no se inventó una nueva sección de portada.
Los ejemplos locales ya existentes siguen identificados como demostración.

## Datos históricos y decisiones bloqueadas

No se tocaron modelos, migraciones, datos existentes, hashes ni asociaciones.
Sociedad previamente asociada sigue visible: no se puede saber retrospectivamente
si fue fallback, regla válida o elección manual. No se falsea esa procedencia.

CAT-02 requiere una propuesta explícita de migraciones nuevas para codigo,
es_general, origen y estado/registro de intentos, con tratamiento conservador de
legado. También debe definir qué significa el estado agregado ante asociaciones
manuales/históricas y un resultado automático vacío. No se deduce ese estado de
procesado_ia ni de que existan o no temas. No se publicaron estados ficticios ni
un endpoint api/categorias sin la identidad estable que requiere su contrato.

Cuatro frente a doce requiere alinear el catálogo aprobado: conservar los cuatro
como iniciales y tratar el resto como extensión/legado hasta su aprobación es una
opción; aprobar explícitamente las doce es otra. Esta fase no elige ni migra datos.
Cambiar de una a múltiples propuestas también exige coordinar prompt/parser,
catálogo vigente y persistencia protegida; no basta con aceptar una lista de nombres.

La función de asociación aún puede reutilizar un tema específico arbitrario y
los formularios actuales permiten editar categorías sin procedencia. Se conservaron
sin ampliar sus permisos ni efectuar reclasificaciones. Implementar selección
fiable de temas generales y reemplazo selectivo exige los campos de CAT-02.

## PR #24

Sus filtros usan IDs reales de Categoria; dashboard_categorias y data-categories
preparados aquí conservan esa forma. Al integrar deben combinarse el prefetch y
los atributos geográficos que añade PR #24 con esta lectura común, sin duplicar
la clasificación ni reemplazar el orden de Fase 2.1. Portada y detalle tienen
cambios adyacentes: conservar categorías múltiples/procedencia junto con tarjetas
enlazadas y funcionalidades de perfil/guardado. No se integró PR #24.

## Pruebas y preparación de PostgreSQL

Ejecuciones locales sin Django, red ni Docker:

- `python3 -B -m unittest discover -s tools/fase2_2 -p 'test_*.py'`: **16/16**.
  Incluye 13 pruebas de clasificador/lector reales con modelos simulados y tres del
  scraper real con ORM simulado. Cubren propuesta incierta, Sociedad con evidencia,
  empates, respuesta parcial, JSON adversarial, asociaciones múltiples y fallo posterior.
- `node tools/fase2_2/test_frontend.js`: **9 escenarios aprobados**, sin DOM ni red.
- `node --check app/static/js/landing-news.js`: correcto.
- Regresiones sin dependencias: arnés **32/32**, ingesta **26/26**, fechas **9/9**.
- Modo `-O`: arnés **32/32**, categorías/clasificación/persistencia **16/16**.
  Compilación estática y git diff --check correctos.

El ajuste de fixture en tools/fase1_2/test_unit.py añade confirmada=True a su
clasificación simulada deliberadamente exitosa; no cambia expectativas de sus 26 pruebas.

Se agregaron **10 pruebas ORM** en core.test_categorias_compat y se seleccionaron
**14 existentes** de core.test_clasificacion: reglas, departamentos, IA simulada y
vinculación. El nuevo bloque Fase 2.2 contiene **24 pruebas**, además de las
64 + 54 + 14 anteriores: **156 esperadas** en total, todavía no ejecutadas para
este cambio. Las 132 aprobadas informadas por el usuario son la base anterior,
no una validación de Fase 2.2. No hay Django instalado en el Python del anfitrión.

Las otras pruebas de scraping del módulo core.test_clasificacion conservan mocks
urllib/sitemaps anteriores al transporte de Fase 1.2; no se incluyeron ni se
reescribieron en este paquete. Por tanto el arnés seleccionado no equivale a la
suite completa del repositorio.

El arnés conserva todos sus controles de aislamiento y agrega sólo una selección
aditiva de tests. No se ejecutaron Docker, bases persistentes, ingestas reales,
HTTP, Gemini, migraciones, commits ni operaciones de historia Git.
Comando preparado para ejecución manual posterior autorizada en el entorno
descartable, con imágenes ya locales y sin sudo:

```sh
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 /usr/bin/python3 -B /home/sebas/Escritorio/trendwatch-pr23-estabilizacion/tools/fase1_1/run.py
```


## Validación integral posterior completada

El usuario confirmó la ejecución satisfactoria de la validación en el entorno
PostgreSQL/PostGIS descartable:

- Fase 1.1: **64/64**.
- Fase 1.2: **54/54**.
- Fase 2.1: **14/14**.
- Fase 2.2: **24/24**.
- Total: **156/156 pruebas aprobadas**.
- Django System Check: **sin incidencias**.

Esta confirmación posterior sustituye el estado pendiente descrito arriba, que
se conserva como historial de preparación. No equivale a conformidad completa
con CAT-01: siguen vigentes todas las observaciones sobre catálogo de cuatro
frente a doce, clasificación múltiple, códigos persistentes, temas generales,
procedencia protegida y estado temático pendientes de CAT-02.

Durante la preparación de este checkpoint no se ejecutaron Docker, scraping,
Gemini, servicios externos ni migraciones. Sólo se actualizó este documento;
el código funcional validado se conserva sin modificaciones adicionales.
