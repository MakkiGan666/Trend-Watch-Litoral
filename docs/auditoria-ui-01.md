# UI-01 — Datos simulados e integración de la portada

Fecha: 15/10/2026. Rama de trabajo: `feature/UI-01`, creada desde `origin/main` en `17bf180` según la salida de Git proporcionada por el responsable.

## Alcance y método

Auditoría de lectura de la portada `/`, sus parciales, estilos, JavaScript, rutas y productores de datos. No se modifican funcionalidades, contratos de API, modelos, migraciones, credenciales ni datos. La implementación corresponde a UI-02 y a las tareas de backend acordadas con el equipo.

Se distingue entre contenido de demostración, configuración estática legítima y datos obtenidos del backend. Tener un endpoint o una consulta ORM no demuestra que haya datos en PostgreSQL ni que el navegador los esté mostrando.

## Resultado principal

La portada mezcla publicaciones consultadas al backend, nueve tarjetas de ejemplo posibles y seis tendencias estáticas. Espera exactamente Salud, Policiales, Turismo y Festividades. El listado general no entrega categorías relacionales: el frontend intenta deducirlas de `fuente`. Esto impide mostrar correctamente publicaciones que sí tengan categorías vinculadas pero cuya fuente no termine con el nombre esperado entre paréntesis. Tampoco se reciben imágenes.

La ausencia de una categoría entre las últimas 20 publicaciones no demuestra que esa categoría esté vacía en toda la base. El contador de la portada representa únicamente las publicaciones recibidas y reconocidas por esas cuatro secciones.

## Inventario de componentes y cambios necesarios

Todas las rutas de archivos de este informe son relativas a la raíz del repositorio.

| Componente | Archivos | Datos actuales y evidencia | Información real necesaria | Cambio propuesto, sin implementar |
|---|---|---|---|---|
| Secciones por categoría | `app/core/templates/inicio.html`, `partials/_news_category.html` dentro de la misma carpeta de templates | Cuatro inclusiones fijas: `salud`, `policiales`, `turismo`, `festividades`. No se consulta un catálogo. | Catálogo de categorías definido por CAT-01/CAT-02, con identificador estable y nombre visible. | Generar secciones desde el catálogo acordado; no cerrar ahora un contrato nuevo de forma unilateral. |
| Noticias reales y agrupación | `app/static/js/landing-news.js`, `app/core/views.py` (`listar_publicaciones`) | GET del listado. Acepta `categorias` como arreglo de nombres o `categoria`; si no hay arreglo, extrae el sufijo de `fuente`. Descarta del render las categorías sin sección. | Categorías relacionales de cada publicación y relación con el catálogo. | Acordar campos y cardinalidad; agrupar por identificadores estables. Distinguir sin categoría de categoría no reconocida. |
| Tarjetas de demostración | `app/static/js/landing-news.js` (`demoTitles`, `allowDemo`, `load`) | Tres títulos por Salud, Turismo y Festividades. En portada, al faltar `data-news-demo="false"`, se habilitan automáticamente cuando el grupo no tiene publicaciones. Policiales no tiene muestras. Aparecen con distintivo, nota y sin enlace de lectura. | Publicaciones reales; vacío explícito cuando no existan resultados. | Decidir con el equipo si retirar las muestras o reservarlas a un modo de demostración explícito. Nunca convertirlas en noticias ni guardarlas en PostgreSQL. |
| Conteo y cobertura | `landing-news.js`, `views.py` (`listar_publicaciones`) | El servidor devuelve las últimas 20 por `fecha_captura`. `total` es la longitud de ese lote. El frontend cuenta IDs únicos de categorías reconocidas y separa las demostraciones. | Total y cobertura por categoría, con filtros o paginación acordados. | Evitar presentar el lote como total global. Una categoría sin coincidencias en ese lote debe describirse como tal. |
| Imágenes de noticias | `landing-news.js`, `app/core/models.py` (`Publicacion`), `views.py` (`noticia`) | El JS admite `imagen_url`, pero el listado no lo devuelve y el modelo revisado no tiene ese campo. El detalle usa `getattr(..., None)`. Se muestra un icono con texto de fuente como alternativa. | URL de imagen obtenida y validada por el backend, si el equipo incorpora ese dato. | Mantener alternativa honesta sin imagen. Registrar la dependencia; no inventar fotos ni modificar modelos/ingesta en UI-01. |
| Panel Trends | `app/core/templates/inicio.html` | Seis enlaces escritos a mano: TurismoMisiones, ObrasPosadas, PrecioYerba, ServiciosEldorado, DengueMisiones y FiestaDelInmigrante. Están identificados como demostración. | Tendencias realmente calculadas y destino de navegación coherente. | Elegir consulta de plantilla o API con el equipo; agregar vacío y error según el mecanismo elegido. |
| Tendencias calculadas sin uso en portada | `app/core/views.py` (`landing`), `inicio.html` | La vista consulta `TemaTrend`, anota `publication_count` y entrega `featured_trends` (hasta seis). La plantilla no utiliza esa variable y conserva su lista fija. | Definición de qué se considera tendencia y cómo representarla. | Conectar el resultado validado o ajustar el productor de datos después de acordar significado y campos. No asumir que el modelo ya equivale al hashtag del mockup. |
| Cotizaciones | `partials/_exchange_rates.html`, `app/static/js/exchange-rates.js`, `app/static/css/exchange-rates.css`, `app/core/services/cotizaciones.py` | No hay precios ficticios incrustados: inicia con guiones y consulta la API. Tres mercados fijos, fecha por fila, respaldo marcado `stale`, reintento y actualización periódica. | GET `/api/cotizaciones/`, respaldado por DolarAPI. | Conservar los estados actuales; validar en ejecución. Los nombres de monedas son configuración, no datos simulados. |
| Cuenta y autenticación | `partials/_account_actions.html`, `partials/_auth_form.html`, `app/static/js/auth-flow.js` | Usuario y visibilidad de Dashboard provienen de sesión/permisos. Login/registro envían POST con CSRF a rutas HTML; no usan JWT desde este flujo. | Sesión y respuestas de login/registro existentes. | No intervenir en autenticación en esta tarea. No etiquetar el nombre de usuario como dato de ejemplo. |
| Notificaciones | `partials/_notification_prompt.html`, `_account_actions.html`, `app/static/js/notification-prompt.js` | Preferencia en almacenamiento del navegador y permiso mediante Notification API. El texto indica que el envío está pendiente. No consulta un servicio de avisos. | Backend de notificaciones si una tarea posterior lo implementa. | Mantener visible la limitación. El permiso concedido no demuestra que se envíen notificaciones. |
| Estructura visual | `app/static/css/trendwatch.css`, `landing-news.css`, `exchange-rates.css`, `auth-flow.css`, `notification-prompt.css` | Definen glass, grillas, carruseles, estados ocultos y tamaños adaptables. No producen noticias ni métricas. Los tres recuadros de `_news_category.html` son una previsualización decorativa, no tres resultados. | Estados de carga, vacío y error coherentes con datos reales. | Reutilizar estilos y parciales en UI-02. Comprobar escritorio y móvil al generar categorías dinámicas. |

## Endpoints y mecanismos consumidos

| Disparador | Método y ruta | Contrato actual / propósito |
|---|---|---|
| Carga de portada y reintento | GET `/api/publicaciones/` | `{status, total, data}`. Cada publicación incluye `id`, `titulo`, `fuente`, `url`, `procesado_ia`, `fecha` y `sentimiento` opcional/nulo. No incluye `categoria`, `categorias` ni `imagen_url`. No hay filtro por categoría ni paginación declarados en esta vista; aplica límite 20. |
| Widget de cotizaciones y reintento | GET `/api/cotizaciones/` | `{status, source, currency, data}`. Filas con `key`, `compra`, `venta`, `fechaActualizacion`, `moneda`, `stale`. Caché de respuesta completa 300 s, incompleta 60 s y respaldo por mercado hasta 24 h. El navegador consulta cada 5 minutos mientras está visible. |
| Envío voluntario del formulario | POST `/login/` o `/registro/` | FormData, CSRF y `X-Requested-With: XMLHttpRequest`; el frontend espera JSON con `success` y eventual `message`. No se realizan envíos de prueba en esta auditoría. |
| Lectura de una tarjeta real | Navegación GET `/noticia/<id>/` | Página HTML del detalle. El navegador no consume `/api/publicaciones/<id>/` para abrir estas tarjetas. |
| Enlace Trends | Navegación `/categorias/#trend-...` | Ancla a tarjetas estáticas de otra página, no consulta de tendencias en la portada. |
| Entrada a un departamento desde Localidades | GET `/api/localidades/<slug>/publicaciones/` desde `localidad.html` | Fuera de la carga de portada; reutiliza `landing-news.js` con `data-news-demo="false"`. Devuelve arreglo `categorias` de nombres, con fallback por fuente. Cambios del JS compartido deben comprobar también esta pantalla. |

En `app/core/urls.py` revisado no hay ruta pública de catálogo de categorías ni de listado de tendencias. Sus nombres y formatos futuros son decisiones de CAT-01/CAT-02, no endpoints existentes. Las URLs RSS y DolarAPI son consultadas por el servidor; no directamente por el feed de noticias del navegador. Fuentes web y recursos estáticos son solicitudes de presentación, no APIs de negocio.

## Inconsistencias de categorías

1. El modelo ya permite varias categorías mediante `Publicacion → PublicacionTema → Tema → Categoria`; el listado general no serializa esas relaciones.
2. La página de detalle usa `_categorias_de_publicacion`, mientras la portada depende del sufijo de `fuente`. Una misma publicación puede mostrar categorías diferentes entre tarjeta y detalle.
3. El scraper principal declara `misiones`, `tecnologia`, `policiales`, `cultura` y `actualidad`. Sólo `policiales` coincide exactamente con las cuatro secciones de portada. Esto es una diferencia de configuración comprobable en código, no un inventario de categorías efectivamente existentes en PostgreSQL.
4. El scraper usa Misiones como fallback para una clave no admitida, pero construye `fuente` con la clave solicitada. No ejecutar ingestas con nombres de la interfaz para intentar corregir esta diferencia; registrar la revisión para el responsable de ingesta.
5. La normalización del JS elimina tildes y cambia a minúsculas, pero no resuelve sinónimos ni cambios de nombre. Si el catálogo devuelve objetos `{id, nombre}` en lugar de cadenas, el código actual no los interpreta correctamente. El formato debe acordarse antes de UI-02.
6. Un arreglo `categorias: []` se considera la lista definitiva: no se usa el sufijo de fuente en ese caso. Definir con backend cómo representar publicaciones todavía sin clasificar.

## Alcance relacionado fuera de portada

`categorias.html`, destino de Trends y Localidades, contiene menciones, porcentajes y tendencias estáticos. `trendwatch.js` calcula un conteo ficticio desde `total = 128` en `initFilters`; ese módulo sale sin actuar cuando no encuentra `#filters` en la portada. No atribuir ese contador a `/`. Estos componentes requieren una tarea de integración propia para evitar que un enlace desde portada termine mostrando métricas simuladas como si fueran reales.

El estado actual de las categorías, las relaciones y los conteos de PostgreSQL debe obtenerse con evidencia del entorno de ejecución o una consulta de sólo lectura autorizada; no puede deducirse del mockup, de la fuente RSS ni de la auditoría anterior del 14/10.

## Orden propuesto de integración

1. **CAT-01:** confirmar catálogo canónico y reglas de clasificación; registrar decisiones pendientes sobre publicaciones sin categoría y múltiples categorías.
2. **CAT-02:** acordar y documentar catálogo/listado de publicaciones, identificadores, filtro, límite/paginación y significado de `total`. No condicionar categorías a un cambio de imágenes.
3. **UI-02:** generar secciones con esos datos, agrupar publicaciones por identidad estable y mostrar carga/vacío/error. Retirar o aislar explícitamente las muestras según decisión del equipo.
4. **Comprobación de integración:** categorías existentes con y sin noticias; sin categoría; múltiples categorías; categoría ajena al catálogo; lote vacío; API caída; título sin imagen y enlace interno; conteo distinto del total global; móvil y escritorio; regresión de Localidades por JS compartido.
5. **Tareas posteriores:** tendencias calculadas y sus enlaces, imágenes reales y métricas de categorías/localidades. Conservar cotizaciones y registrar notificaciones como preferencia local hasta implementar entrega real.

## Evidencia y limitaciones

- Revisión estática de `inicio.html`, parciales de noticias/cotizaciones/cuenta/autenticación/notificaciones, los cinco JS cargados, los cinco CSS cargados y productores de datos en vistas, rutas, modelos y servicios.
- Búsqueda de `fetch`, rutas, arreglos de demostración, categorías, relaciones e imágenes. Confirmadas las dos consultas GET automáticas de negocio de portada y los POST de autenticación condicionados al usuario.
- Intento de GET de `/`, `/api/publicaciones/`, `/api/cotizaciones/` y `/api/localidades/capital/publicaciones/` el 15/10/2026: conexión rechazada en `127.0.0.1:8000` (WinError 10061). No se obtuvo respuesta HTTP ni acceso a datos de la base en ese intento. Esto no demuestra un defecto de los endpoints.
- Comprobación posterior el 15/10/2026, tras restablecer la conexión local con PostgreSQL: GET `/` respondió HTTP 200; GET `/api/publicaciones/` respondió HTTP 200, `status: success`, `total: 10` y diez elementos. Todos declararon `fuente: El Territorio (Policiales)`. Los campos recibidos fueron `fecha`, `fuente`, `id`, `procesado_ia`, `sentimiento`, `titulo` y `url`; ninguno de los diez elementos incluyó `categoria`, `categorias` o `imagen_url`.
- El detalle HTML de la primera publicación recibida respondió HTTP 200. GET `/api/cotizaciones/` respondió HTTP 200, `status: success` y tres elementos. GET `/api/localidades/capital/publicaciones/` respondió HTTP 200, `status: success`, `total: 0` y arreglo vacío. Esto demuestra disponibilidad y contenido de esas respuestas en la comprobación local, no cobertura de toda la base ni asignación relacional de las noticias.
- Con ese lote y las reglas del JS revisado, se esperan diez noticias en Policiales y nueve tarjetas de demostración en las otras tres secciones. Es una deducción del código y el JSON observado, no una comprobación visual del DOM ejecutado. No se inspeccionó el navegador ni se consultaron directamente las tablas de PostgreSQL.
- No se ejecutan ingesta, análisis IA, pruebas que creen publicaciones ni envíos de formularios. No se modifican datos. La suite completa no se ejecuta para esta revisión documental; resultados históricos del equipo no se presentan como una ejecución actual.

### Reproducción al disponer de Docker

Con la instalación actualizada y el servidor ya preparado, abrir `/` y revisar en DevTools → Network las consultas de publicaciones y cotizaciones. Guardar estado HTTP y estructura sin credenciales. Inspeccionar categorías/imágenes recibidas, contador de tarjetas reales y etiquetas de demostración. Abrir un detalle y comparar la categoría. No ejecutar endpoints de ingesta o mutación para esta comprobación.

Para demostrar si faltan relaciones en la base, pedir al responsable CAT evidencia de sólo lectura del catálogo y de las relaciones de las publicaciones; la ausencia del campo en el JSON general no demuestra ausencia de relaciones en PostgreSQL.

## Checklist de UI-01

- [x] Revisar archivos de portada HTML, CSS y JavaScript.
- [x] Identificar componentes simulados o estáticos y distinguir configuración legítima.
- [x] Identificar endpoints y mecanismos consumidos por el código.
- [x] Registrar inconsistencias del contrato y categorías esperadas.
- [x] Documentar archivos afectados, cambios necesarios y orden de integración.
- [x] Guardar el informe técnico en el repositorio de trabajo.
- [x] Completar evidencia HTTP de ejecución con servidor disponible, dejando explícitos los límites de la revisión visual y relacional.
- [ ] Subir la rama, abrir PR, compartir con el equipo y mover la tarjeta a En revisión (a cargo del responsable).
