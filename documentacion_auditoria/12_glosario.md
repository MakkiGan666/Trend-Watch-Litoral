# 12 — Glosario técnico

| Término | Significado en este proyecto |
|---|---|
| **Administrador** | Grupo de Django con los permisos de `PERMISOS_ADMINISTRADOR` (`core/roles.py`); da acceso al panel, al dashboard, a la IA y a la moderación |
| **Advisory lock** | Bloqueo cooperativo de PostgreSQL (`pg_advisory_xact_lock`) usado por `serializar_identidad` para serializar altas y cambios de username y email |
| **Blacklist (JWT)** | Tablas de `rest_framework_simplejwt.token_blacklist` que registran los refresh tokens revocados |
| **Categoría** | Una de las 12 categorías temáticas de `CATEGORIAS_PROYECTO`. Se asocia a una publicación mediante `Tema` y `PublicacionTema` |
| **CAT-01** | Especificación de categorías en `docs/categorias/`. Propone 4 categorías y un contrato REST que el código no implementa |
| **Clic / lectura** | `ClicPublicacion`: lectura única de una noticia por usuario autenticado; base de las tendencias |
| **Columna generada** | `GeneratedField` persistido (`titulo_busqueda`, `contenido_busqueda`) que la base calcula a partir de otra columna |
| **Confirmada (categoría)** | Clasificación segura (por sección, por reglas con evidencia en el título, o validada de Gemini) que se guarda. Las no confirmadas no se guardan |
| **Departamento** | Una de las 17 divisiones administrativas de Misiones en `localidades.DEPARTAMENTOS`, identificada por un slug (`capital`, `obera`, `25mayo`…) |
| **Destacadas** | Noticias elegidas para la portada por `relevancia._puntaje` (clics recientes, territorio, mención de Misiones, antigüedad) |
| **El Territorio** | Diario de Misiones; única fuente de noticias implementada |
| **Embeddings** | Vectores numéricos que representan el significado de un texto. **No se usan** en el proyecto |
| **Fecha efectiva** | `fecha_publicacion` si existe; si no, `fecha_captura` (`fechas.fecha_efectiva`) |
| **Gemini** | Modelo de IA de Google usado para sentimiento, localidades, categorías dudosas y departamentos |
| **`hash_origen`** | SHA-256 de la URL (ingesta) o de `url or titulo` (alta manual). Identidad única de una publicación |
| **Idempotente** | Operación que puede repetirse sin efectos adicionales (por ejemplo, `analizar_sentimiento_comentarios`, `configurar_roles`) |
| **Ingesta** | Proceso de descarga, validación, deduplicación, clasificación y guardado de noticias (`services/scraper.py`) |
| **JWT** | JSON Web Token: credencial de la API (`Authorization: Bearer <access>`) |
| **Léxico (método)** | Análisis de sentimiento por lista de palabras (`analyze_sentiment_lexicon`), sin red ni modelo |
| **Locación** | `Locacion`: lugar (≤18 caracteres) con coordenadas, extraído por Gemini de una noticia |
| **Lote (`_Lote`)** | Una ejecución de ingesta, registrada en `RegistroDatos`, con contadores y errores |
| **Moderación** | Revisión humana de comentarios (`pendiente` → `publicado` o `rechazado`) desde Django Admin |
| **newspaper3k** | Biblioteca que extrae título, texto, fecha e imagen de una página de noticia |
| **Ollama** | Servidor local de modelos de lenguaje; aquí analiza comentarios con `llama3.1:latest` |
| **PERMISOS_PANEL** | Los cuatro permisos CRUD de `publicacion` necesarios para el panel y el dashboard |
| **Plegado (texto)** | Normalización NFC, minúsculas y vocales sin tilde (`plegar_v1`) para comparar sin distinguir acentos |
| **Polaridad** | Valor de sentimiento en [-1, 1]: negativo, neutral (en torno a 0) o positivo |
| **PostGIS** | Extensión geográfica de PostgreSQL incluida en la imagen Docker; **no se usa** en el código |
| **`procesado_ia`** | Indicador de que la publicación ya tiene sentimiento (léxico o Gemini); las pendientes son las que tienen `False` |
| **Prompt injection** | Intento de que un texto analizado dé órdenes al modelo; mitigado con advertencias en el prompt y validación estricta de salida |
| **RAG** | *Retrieval-Augmented Generation*: generación de texto con documentos recuperados. **No está implementado** |
| **RegistroDatos** | Tabla de auditoría de cada ejecución de ingesta (fuente, fecha, estado) |
| **RevisionDepartamento** | Decisión auditable (reglas o IA, con estado, lugar, evidencia e historial) para noticias sin departamento |
| **RSS** | Formato XML de los feeds de El Territorio |
| **Savepoint** | Punto de restauración dentro de una transacción; cada noticia del lote se guarda en uno propio |
| **SentimientoComentario** | Resultado automático (Ollama o léxico) del sentimiento y la categoría de un comentario |
| **Sitemap** | Índice XML de URLs del sitio, usado por la ingesta histórica |
| **SSRF** | *Server-Side Request Forgery*; `descarga_segura.py` lo previene con lista blanca de hosts y validación de IP |
| **Superusuario** | Cuenta Django con todos los permisos; la única que edita usuarios y grupos en el Admin |
| **Tema** | Entidad intermedia entre `Categoria` y `Publicacion` (y entre `Categoria` y `Trend`) |
| **Tendencia** | Noticias más leídas en 7 días (`tendencias_destacadas`), o "estimadas" si no hay lecturas |
| **`texto_hash`** | SHA-256 del texto de un comentario; indica si su análisis sigue vigente |
| **Usuario (rol)** | Grupo de Django con solo `core.view_publicacion` |
| **Valoración** | Voto manual del lector (positivo, neutral o negativo) sobre una noticia |
| **Vigente (análisis)** | Análisis procesado cuyo `texto_hash` coincide con el texto actual del comentario |
