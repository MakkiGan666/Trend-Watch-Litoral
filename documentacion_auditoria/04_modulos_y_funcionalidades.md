# 04 — Módulos, funcionalidades y estado de implementación

Clasificación usada:
**Implementada** (código completo y enrutado o invocable) · **Parcial** (existe, pero incompleta o con
limitaciones relevantes) · **Planificada** (aparece en documentos o requisitos, sin código) ·
**Experimental / sin uso** (código presente pero no conectado, legacy o desactivable).

"Implementada" significa que el código existe y está conectado. **No** significa que se haya verificado
su ejecución: esta auditoría no ejecutó la aplicación.

## 1. Sistema de usuarios

| Funcionalidad | Estado | Evidencia |
|---|---|---|
| Registro público (AJAX) | Implementada | `views.registro_view`: valida longitud, unicidad sin distinguir mayúsculas, `errores_identidad`, `validate_password`, `EmailValidator`; inicia sesión al crear. Decorada con `con_identidad_serializada` |
| Login con username **o** email | Implementada | `services/autenticacion.autenticar_identificador`: rechaza identificadores ambiguos y calcula un hash simulado para igualar tiempos |
| Logout HTML | Implementada | `views.logout_view`. Acepta cualquier método HTTP, incluido GET |
| Perfil: nombre, apellido, email, fecha de nacimiento, celular | Implementada | `views_perfil.perfil`, `forms_perfil.PerfilForm`, modelo `PerfilUsuario`. Cambiar el email exige la contraseña actual |
| Cambio de contraseña | Implementada | `PasswordChangeForm` + `update_session_auth_hash` |
| Noticias guardadas | Implementada | `PublicacionGuardada`, `views_perfil.guardar_publicacion` |
| Recomendaciones (3) por afinidad | Implementada | `views_perfil.perfil` sección `guardados`: categorías y departamentos de guardados y positivos, excluyendo negativos |
| Sección "notificaciones" del perfil | Parcial | Ruta `perfil_notificaciones`. Solo preferencia del navegador (`notification-prompt.js`); no hay notificaciones del servidor |
| Alta de administradores desde la web | Implementada (sin commitear) | `views_administradores.gestion_administradores`: verifica que el grupo Administrador tenga **exactamente** `PERMISOS_ADMINISTRADOR` y registra un `LogEntry` |

## 2. Roles, permisos y panel administrativo

| Funcionalidad | Estado | Evidencia |
|---|---|---|
| Roles Usuario y Administrador (grupos Django) | Implementada | `roles.py` `PERMISOS_ROLES`; `configurar_roles` |
| Panel de publicaciones con filtros (texto, fecha, fuente, categoría, localidad) y paginación de 25 | Implementada | `views.publicaciones`, `forms.FiltrosPublicaciones` |
| CRUD web de publicaciones | Implementada | `crear_publicacion_view`, `editar_publicacion_view`, `eliminar_publicacion_view`; `PublicacionForm` admite imagen ≤5 MB (JPEG, PNG o WebP verificados por contenido) |
| Dashboard analítico | Implementada | `views_dashboard.dashboard`: barras por categoría, fuente, departamento y sentimiento; serie diaria o mensual en SVG |
| Indicadores en la portada | Implementada | `_inicio_indicadores.html`, `indicadores.resumen_publicaciones`. El texto dice "exclusivo de superusuarios", pero el código lo muestra a quien tenga `PERMISOS_PANEL` (también a Administrador) |
| Django Admin personalizado | Implementada | `admin.py`: hash de origen al crear, sentimiento único, `RevisionDepartamento` de solo lectura, sin borrado de `RegistroDatos` ni `Sentimiento`, usuarios y grupos editables solo por superusuarios |
| Moderación de comentarios | Implementada | Acciones `aprobar` y `rechazar` de `ComentarioAdmin`, con bloqueo y `log_change` |

## 3. Publicaciones, categorías y departamentos

| Funcionalidad | Estado | Evidencia |
|---|---|---|
| 12 categorías del proyecto | Implementada | `clasificacion.CATEGORIAS_PROYECTO`: Salud, Policiales, Turismo, Economía, Política, Educación, Tecnología, Sociedad, Cultura, Ambiente, Deportes, Festividades |
| Página por categoría (24 por página) | Implementada | `views.publicaciones_categoria`, `categoria_noticias.html` |
| 17 departamentos de Misiones con municipios | Implementada | `localidades.DEPARTAMENTOS` (fuente citada: digestomisiones.gob.ar) |
| Página y API por departamento | Implementada | `views.localidad`, `views.publicaciones_localidad` (por `departamento` o por `Locacion` mapeada) |
| Mapa de departamentos | Parcial | `categories-map.js` y `categorias.html`: puntos de referencia y tarjetas. Sin métricas por mapa ni capas GIS |
| Contrato CAT-01 (`codigo`, `estado_clasificacion`, `GET /api/categorias/`, `Tema.es_general`, `PublicacionTema.origen`) | **Planificada, no implementada** | `docs/categorias/CAT-01-especificacion.md` frente a `models.py`. Además, CAT-01 define **4** categorías y el código usa **12** |

## 4. Ingesta y procesamiento

Detalle completo en [06](06_ingesta_y_procesamiento.md).

| Funcionalidad | Estado |
|---|---|
| RSS de 9 secciones de El Territorio | Implementada |
| Ingesta histórica por sitemaps | Implementada |
| Ejecución periódica (servicio Compose `ingesta`, bucle de 300 s) | Implementada; sin commitear en esta rama y con `DB_HOST` local incorrecto (ver [11](11_problemas_y_recomendaciones.md)) |
| Scheduler del sistema (cron, Celery beat) | No existe; el bucle es un `while True` |
| Ingesta de redes sociales | Planificada (solo hay un diccionario `REDES_SOCIALES`) |
| Fuentes configurables desde la interfaz | Planificada; las fuentes están fijas en el código |
| Recuperación de imágenes faltantes | Implementada (`recuperar_imagenes`, solo Policiales) |
| Revisión territorial con IA | Implementada (`revisar_departamentos`, `RevisionDepartamento`) |
| Scraper alternativo `scrapers/noticias.py` | Experimental / legacy: no se usa desde vistas ni comandos, solo desde pruebas. Usa el ID numérico de la URL como clave primaria (ver [11](11_problemas_y_recomendaciones.md)) |

## 5. Comentarios, valoraciones e interacción

| Funcionalidad | Estado | Evidencia |
|---|---|---|
| Comentarios (≤2000 caracteres), paginados de a 10 | Implementada | `views_comentarios`, `Comentario` |
| Moderación previa | Implementada | `Comentario.estado` vale `pendiente` por defecto. Solo se muestran los `publicado` y los propios del autor. Editar vuelve a `pendiente` |
| Filtro de lenguaje ofensivo | Implementada | `moderacion_comentarios.contiene_lenguaje_inapropiado` en `ComentarioForm.clean_texto` (rechaza el envío). La migración `0015` aplicó la misma lista a los comentarios existentes |
| Sentimiento automático de comentarios | Implementada | `analisis_automatico.programar_analisis` en `on_commit`. Desactivable con `SENTIMIENTO_COMENTARIOS_AUTOMATICO=0` |
| Valoración del lector (positivo, neutral o negativo) | Implementada | `ValoracionPublicacion`, `views_valoraciones` (una por usuario y noticia, retirable) |
| Lecturas únicas (clics) | Implementada | `relevancia.registrar_clic`: una fila por usuario y noticia, `ultima_visita` se renueva cada >1 día. No cuenta superusuarios ni anónimos |

## 6. Inteligencia artificial y sentimiento

Detalle en [07](07_inteligencia_artificial_y_RAG.md).

| Funcionalidad | Estado |
|---|---|
| Sentimiento de noticias con léxico local (alta manual y reprocesamiento) | Implementada |
| Sentimiento y localidades de noticias con Gemini (`procesar_pendientes`) | Implementada |
| Categoría de noticias dudosas con Gemini | Implementada (opcional, `usar_ia`) |
| Departamento con Gemini y cita verificada | Implementada (solo por comando) |
| Sentimiento y categoría de comentarios con Ollama | Implementada, con respaldo léxico |
| Métricas probabilísticas por lote (`/api/sentiment/batch-analyze/`) | Implementada; pensada para "comentarios de redes sociales", pero recibe el texto en el cuerpo de la petición y no lo persiste |
| Resumen automático con IA (requisito 2.0) | Planificada |
| Insights con IA (2.1) | Planificada |
| **Embeddings, búsqueda semántica, RAG** | **No existen**. El nombre de rama `feat/llm-rag-interacciones` no se refleja en el código |

## 7. Búsqueda

| Funcionalidad | Estado | Evidencia |
|---|---|---|
| Búsqueda por palabras (todas deben aparecer) sin distinguir tildes ni mayúsculas | Implementada (sin commitear) | `buscador.publicaciones_coincidentes` sobre las columnas generadas `titulo_busqueda` y `contenido_busqueda` |
| Página HTML con resaltado | Implementada | `views_buscador.buscar_noticias`, `presentacion_busqueda.segmentos_resaltados` |
| API JSON paginada (20) | Implementada | `views_buscador.buscar_publicaciones` |
| Autocompletado de términos y noticias | Implementada | `sugerencias.sugerir` (SQL por motor) |
| Ranking por relevancia, búsqueda difusa o semántica | No existe; el orden es por fecha |

## 8. Estadísticas y tendencias

| Funcionalidad | Estado | Evidencia |
|---|---|---|
| Destacadas por categoría (15 cada una) | Implementada | `relevancia.noticias_destacadas_por_categoria`: puntaje por clics de 7 días, departamento, mención de Misiones y antigüedad |
| Tendencias (5) | Parcial | `relevancia.tendencias_destacadas`: más leídas en 7 días. Si no hay lecturas, se "estiman" con las destacadas (`estimada=True`). El modelo `Trend` solo guarda la clave `lecturas_7_dias` |
| Indicadores diarios, semanales, mensuales y anuales (3.1) | Parcial | El dashboard agrupa por día o por mes automáticamente (más de 120 días → mes); no hay vistas semanales ni anuales |
| Reportes descargables (3.1.3) | Planificada |
| Alertas por relevancia crítica (3.1.4) | Planificada (`notification-prompt.js` solo pide permiso al navegador) |
| Temas emergentes (4.0), comparación entre localidades (4.1), predicción (4.2) | Planificadas |
| Cotizaciones del dólar y del real | Implementada (`/api/cotizaciones/`, panel en la portada) |

## 9. Interfaces públicas y privadas

- **Públicas, sin sesión:** portada, categorías, detalle de noticia, localidad, búsqueda, API de lectura
  (listado, detalle, búsqueda, sugerencias, localidad, cotizaciones).
- **Con sesión de lector:** comentar, editar y borrar comentarios propios, valorar, guardar, perfil.
- **Administrador:** panel de publicaciones, dashboard, `/procesar-ia/`, alta de administradores,
  Django Admin (moderación).
- **Superusuario:** además, edición de usuarios y grupos en Django Admin.
- **API con JWT:** CRUD de publicaciones, ingesta, sentimiento, perfil propio, logout.

## 10. Código legacy o sin uso

| Elemento | Situación |
|---|---|
| Modelos `Role`, `User` (tabla `"User"`), `VotoPublicacion`, `Auditoria`, `UserAuditoria` | Esquema heredado del diagrama ER. No los usa la lógica de negocio (solo `admin.py`). `User.email` tiene `max_length=20`. No es el usuario de autenticación |
| `Locacion.latitud` y `longitud` | Las escribe Gemini, pero ninguna vista usa las coordenadas para un mapa |
| `scrapers/noticias.py` | Scraper alternativo legacy, solo cubierto por pruebas |
| `gemini_cliente.disparar_ingesta` | Vista duplicada no enrutada (la ruta usa `views.disparar_ingesta`); se importa en pruebas |
| Plantillas `landing.html`, `litoral.html`, `login.html` | Ninguna vista las renderiza |
| `fixtures/roles.json` | Histórica; el README pide no cargarla |
| Grupos históricos `Lector` y `Analista` | Conservados en bases antiguas, fuera de `PERMISOS_ROLES` |
| Dependencias `pandas`, `scipy`, `feedparser` | Declaradas, no importadas |
