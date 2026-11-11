# 03 — Estructura del proyecto

## 1. Árbol de directorios (sin `.git`, `venv`, `__pycache__` ni imágenes)

```
Trend-Watch-Litoral/
├── .devcontainer/devcontainer.json   Dev container sobre el servicio web de Compose
├── .env                              Configuración local con secretos (no rastreado; no se leyeron sus valores)
├── .env.example                      Plantilla de variables
├── .gitignore / .dockerignore
├── AGENTS.md                         Guía para contribuidores y agentes
├── README.md                         Instalación, JWT, roles, sentimiento de comentarios
├── Dockerfile                        Imagen de desarrollo (python:3.13-slim)
├── Dockerfile.production             Imagen productiva (gunicorn, usuario 10001)
├── docker-compose.yml                Desarrollo: db, web, ingesta (modificado localmente)
├── compose.production.yml            Producción: solo web, BD externa
├── requirements.txt / requirements-production.txt
├── test_ingesta.py                   Prueba manual HTTP (pytest + requests) contra un servidor en marcha
├── diff_gemini.txt                   Diff en UTF-16 de gemini_cliente.py (residuo de trabajo, sin seguimiento)
├── grep.exe.stackdump                Volcado de un fallo de grep de MSYS (residuo, sin seguimiento)
├── drawio/ENTIDADRELACION.drawio     Diagrama entidad-relación
├── docs/                             Documentación funcional, auditorías, capturas y prototipo JSX
├── tools/                            Arneses de validación por fase (fase1_1 … fase3_3, buscador, gestion_administradores)
└── app/
    ├── manage.py
    ├── db.sqlite3                    Vacío (0 bytes), ignorado por git
    ├── media/publicaciones/          Imágenes subidas desde el panel (1 archivo)
    ├── mi_proyecto/                  settings.py, settings_production.py, production_config.py, urls.py, wsgi.py, asgi.py
    ├── static/
    │   ├── css/ (21 hojas)  js/ (13 scripts)  img/  mockup/ (fondos de los 17 departamentos)
    └── core/
        ├── models.py  admin.py  apps.py  urls.py
        ├── views.py  views_buscador.py  views_comentarios.py  views_valoraciones.py
        ├── views_perfil.py  views_dashboard.py  views_administradores.py
        ├── forms.py  forms_perfil.py  serializers.py  permissions.py  roles.py
        ├── categorias.py  fechas.py  localidades.py  busqueda_texto_v1.py  presentacion_busqueda.py
        ├── services/   (19 módulos; ver abajo)
        ├── scrapers/noticias.py          Scraper alternativo legacy
        ├── management/commands/ (9 comandos)
        ├── migrations/ (0001 … 0019, con dos fusiones)
        ├── templatetags/roles.py
        ├── fixtures/roles.json           Fixture histórica (el README desaconseja cargarla)
        ├── templates/ (+ core/, partials/)
        └── test_*.py, tests.py, test_auth_flow.js
```

Fuera del repositorio, en `C:\Users\sofia\OneDrive\Escritorio\Proyecto\`, hay otros elementos:
`.venv/`, `Informe_Estado_TrendWatch.pdf` (no leído), `respaldos-trendwatch-2026-11-01/` (parches) y
`respaldos-trendwatch-2026-11-02/`, que contiene un volcado de base de datos (`db-antes-actualizacion.dump`)
y parches de cambios locales. Esos respaldos no se abrieron.

## 2. Servicios (`app/core/services/`)

| Módulo | Responsabilidad |
|---|---|
| `scraper.py` | Ingesta RSS y por sitemaps, deduplicación, registro de lote (`_Lote`) |
| `descarga_segura.py` | Transporte HTTPS restringido a El Territorio (anti-SSRF, límite de tamaño y tiempo) |
| `clasificacion.py` | Categoría por reglas o Gemini, departamento por reglas, vínculo Publicación→Tema→Categoría |
| `clasificacion_departamentos.py` | Revisión de departamento con Gemini y validación de evidencia citada |
| `gemini_cliente.py` | Cliente Gemini, reintentos, saneamiento de errores, sentimiento y localidades de noticias |
| `resultado_ia.py` | Traducción del estado de un lote de IA a código HTTP |
| `sentimiento.py` | Léxico de sentimiento y métricas probabilísticas (t-Student, Wilson) |
| `integridad_sentimiento.py` | Validación numérica y unicidad del `Sentimiento` por publicación |
| `sentimiento_comentarios.py` | Sentimiento y categoría de comentarios (Ollama o léxico), persistencia e idempotencia |
| `analisis_automatico.py` | Cola en memoria con un hilo trabajador para analizar comentarios |
| `moderacion_comentarios.py` | Filtro de lenguaje ofensivo |
| `buscador.py` | Búsqueda por términos sobre columnas generadas plegadas |
| `sugerencias.py` | Autocompletado de términos (SQL nativo PostgreSQL o SQLite) y noticias |
| `relevancia.py` | Noticias destacadas, tendencias por lecturas, registro de clics |
| `indicadores.py` | Resumen total, analizadas, pendientes e inconsistentes |
| `cotizaciones.py` | Cotizaciones de DolarAPI con caché |
| `autenticacion.py` | Login por username o email, sin ambigüedades |
| `identidad.py` | Serialización de altas y cambios de identidad (advisory lock en PostgreSQL) |
| `parametros.py` | Validadores de enteros y segundos |

## 3. Comandos de gestión (`app/core/management/commands/`)

| Comando | Propósito | Escribe en BD |
|---|---|---|
| `ejecutar_scraper` | Ingesta RSS de una categoría o de todas (`--todas`, `--sin-ia`, `--limit`) | Sí |
| `ingestar_historico` | Ingesta por sitemaps entre fechas (`--desde`, `--hasta`, `--limite`) | Sí |
| `ingestar_recientes` | Bucle de RSS cada 300 s (`--una-vez`, `--intervalo` ≥60, `--con-ia`) | Sí (sin commitear) |
| `run_pipeline` | Ingesta RSS seguida de Gemini (lote de 10) | Sí |
| `analizar_sentimiento_comentarios` | Respaldo idempotente del análisis de comentarios (`--metodo ia/lexicon`, `--dry-run`) | Sí |
| `revisar_departamentos` | Reglas o Gemini para noticias sin departamento; por defecto simula | Solo con `--aplicar` |
| `recuperar_imagenes` | Recupera `og:image` de noticias de Policiales sin foto; por defecto simula | Solo con `--aplicar` |
| `configurar_roles` | Crea y actualiza los grupos Usuario y Administrador; asigna un rol | Sí |
| `medir_buscador` | Diagnóstico de rendimiento, solo en una base PostgreSQL marcada como desechable; revierte | Transacción revertida |

## 4. Rutas URL (`app/core/urls.py` + `app/mi_proyecto/urls.py`)

| Ruta | Vista | Acceso |
|---|---|---|
| `/` | `views.landing` (plantilla `inicio.html`) | Público |
| `/categorias/` | `views.categorias` | Público |
| `/categorias/<slug>/` | `views.publicaciones_categoria` | Público |
| `/noticia/<pk>/` | `views.noticia` | Público (registra el clic si hay sesión) |
| `/noticia/<pk>/comentarios/` | `views_comentarios.crear_comentario` | Sesión, POST |
| `/noticia/<pk>/valoracion/` | `views_valoraciones.valorar_noticia` | Sesión, POST |
| `/noticia/<pk>/guardar/` | `views_perfil.guardar_publicacion` | Sesión, POST |
| `/comentarios/<pk>/editar/`, `/eliminar/` | `views_comentarios` | Autor; moderador para eliminar |
| `/litoral/` | Redirige a `/categorias/#localidades` | Público |
| `/localidad/<slug>/` | `views.localidad` | Público |
| `/buscar/` | `views_buscador.buscar_noticias` (HTML) | Público |
| `/perfil/`, `/perfil/guardados/`, `/perfil/notificaciones/` | `views_perfil.perfil` | Sesión |
| `/login/`, `/registro/`, `/logout/` | `views` | Público |
| `/publicaciones/` | `views.publicaciones` (panel) | `PERMISOS_PANEL` |
| `/publicaciones/crear/`, `/<pk>/editar/`, `/<pk>/eliminar/` | Panel CRUD | `add`, `change` o `delete` de `publicacion` |
| `/dashboard/` | `views_dashboard.dashboard` | `PERMISOS_PANEL` |
| `/administradores/` | `views_administradores.gestion_administradores` | Superusuario o Administrador con `auth.add_user` |
| `/procesar-ia/` | `views.procesar_ia` | `core.procesar_ia`, POST |
| `/api/publicaciones/` | `views.listar_publicaciones` | **Público** (últimas 150) |
| `/api/publicaciones/<pk>/` | `views.obtener_detalle_publicacion` | **Público** |
| `/api/publicaciones/buscar/` | `views_buscador.buscar_publicaciones` | Público |
| `/api/publicaciones/sugerencias/` | `views_buscador.sugerencias_publicaciones` | Público |
| `/api/localidades/<slug>/publicaciones/` | `views.publicaciones_localidad` | Público |
| `/api/cotizaciones/` | `views.cotizaciones` | Público |
| `/api/publicaciones/crear/` | `views.crear_o_ingestar_publicacion` | JWT + `add_publicacion` |
| `/api/publicaciones/<pk>/actualizar/` | `views.actualizar_publicacion` (PUT/PATCH) | JWT + `change_publicacion` |
| `/api/publicaciones/<pk>/eliminar/` | `views.eliminar_publicacion` (DELETE) | JWT + `delete_publicacion` |
| `/api/publicaciones/ingestar/<categoria>/` | `views.disparar_ingesta` | JWT + `ejecutar_scraping` + `procesar_ia` |
| `/api/publicaciones/<pk>/procesar-sentimiento/` | `ProcesarSentimientoPublicacionView` | JWT + `procesar_ia` |
| `/api/sentiment/batch-analyze/` | `BatchSentimentAnalysisView` | JWT + `procesar_ia` |
| `/api/auth/login/`, `/refresh/`, `/logout/`, `/me/` | Simple JWT y vistas propias | Ver [08](08_seguridad_y_permisos.md) |
| `/admin/` | Django Admin | `is_staff` + permisos |
| `/media/…` | `static()` de Django | Solo funciona con `DEBUG=True` |

**Discrepancia:** la tabla de rutas de `README.md` lista 9 rutas y omite buscador, perfil, comentarios,
valoraciones, administradores y casi toda la API. También describe `/litoral/` como "mapa Litoral", cuando
en el código es una redirección.

## 5. Plantillas (`app/core/templates/`)

- `inicio.html`: portada; documento HTML completo que **no** extiende `base.html`. Incluye
  `_inicio_categoria`, `_tendencia_card`, `_exchange_rates`, `_auth_modal`, `_notification_prompt`,
  `_inicio_indicadores`, búsqueda y navegación de administradores.
- `base.html`: el resto de las páginas lo extienden (`categorias`, `categoria_noticias`, `noticia`,
  `localidad`, `core/*`, `403`).
- `403.html`: Django la usa automáticamente ante `PermissionDenied`.
- **Plantillas sin uso desde vistas:** `landing.html`, `litoral.html` y `login.html`. Ninguna vista las
  renderiza (`landing` usa `inicio.html`, `litoral` redirige y `login_view` no renderiza plantilla propia).
- `partials/`: 22 fragmentos (comentarios, valoraciones, búsqueda, autenticación, tarjetas regionales,
  indicadores, cotizaciones, aviso de notificaciones, entre otros).

## 6. JavaScript (`app/static/js/`)

| Script | Función | Llama a |
|---|---|---|
| `auth-flow.js` | Modal de login y registro por AJAX | `/login/`, `/registro/` |
| `landing-news.js` | Listado de noticias por departamento | `data-news-feed` → `/api/localidades/<slug>/publicaciones/` |
| `news-search.js` | Búsqueda y autocompletado | `/api/publicaciones/sugerencias/` |
| `exchange-rates.js` | Panel de cotizaciones | `/api/cotizaciones/` |
| `news-detail.js` | Interacciones del detalle (formularios) | `form.action` |
| `home-category-carousel.js` | Carruseles de la portada | — |
| `categories-map.js`, `categories-navigation.js` | Mapa y navegación de departamentos | — |
| `dashboard*.js` | Calendario, selector de localidad y panel | — |
| `notification-prompt.js` | Permiso de notificaciones del navegador y preferencia local | `Notification` API, `localStorage` |
| `trendwatch.js` | Comportamiento general | — |
