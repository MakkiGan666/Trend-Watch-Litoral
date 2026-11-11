# 01 — Resumen ejecutivo

## Qué es TrendWatch Litoral

TrendWatch Litoral es una aplicación web **Django monolítica** (backend y frontend con plantillas en un
solo proyecto) que recolecta noticias del diario **El Territorio** (Misiones, Argentina), las clasifica por
**categoría temática** y por **departamento de Misiones**, calcula **sentimiento**, y las presenta en un
portal público con búsqueda, comentarios moderados, valoraciones, perfiles de lector y un panel para
administradores.

**Problema que aborda** (según `docs/trazabilidad-requisitos.md` y el código): concentrar y ordenar
información regional dispersa para observar temas, territorio y tono de la cobertura de noticias de
Misiones.

## Qué hace hoy (verificado en el código)

| Área | Estado | Evidencia principal |
|---|---|---|
| Ingesta RSS de El Territorio (9 feeds) | Implementada | `app/core/services/scraper.py` → `fetch_and_store_elterritorio` |
| Ingesta histórica por sitemaps | Implementada | `scraper.py` → `ingestar_historico_elterritorio`; comando `ingestar_historico` |
| Ingesta periódica (bucle cada 5 min) | Implementada; sin commitear | comando `ingestar_recientes`, servicio `ingesta` en `docker-compose.yml` |
| Categoría temática (12 categorías) | Implementada (reglas + Gemini opcional) | `services/clasificacion.py` |
| Departamento (17 departamentos) | Implementado (reglas) + revisión con Gemini por comando | `clasificacion.py`, `clasificacion_departamentos.py`, `revisar_departamentos` |
| Sentimiento de noticias | Implementado: léxico local y Gemini | `services/sentimiento.py`, `services/gemini_cliente.py` |
| Sentimiento de comentarios | Implementado: Ollama local con respaldo léxico | `services/sentimiento_comentarios.py`, `services/analisis_automatico.py` |
| Búsqueda y autocompletado | Implementados; sin commitear en esta rama | `services/buscador.py`, `services/sugerencias.py` |
| Comentarios con moderación previa | Implementados | `views_comentarios.py`, `ComentarioAdmin` |
| Valoraciones, guardados, perfil | Implementados | `views_valoraciones.py`, `views_perfil.py` |
| Panel de publicaciones y dashboard analítico | Implementados | `views.publicaciones`, `views_dashboard.dashboard` |
| Roles Usuario/Administrador, sesión y JWT | Implementados | `roles.py`, `serializers.py`, `configurar_roles` |
| Tendencias | Parcial: basadas en lecturas de usuarios | `services/relevancia.py` |
| **RAG, embeddings, búsqueda semántica** | **No existen en el código** | ver [07](07_inteligencia_artificial_y_RAG.md) |
| Resúmenes con IA, alertas, reportes, predicción | No implementados | ver [04](04_modulos_y_funcionalidades.md) |

## Tecnología

Python 3.13 (Docker) · Django 6.1.2 · Django REST Framework 3.18.3 · Simple JWT 5.5.1 · PostgreSQL 17
(imagen PostGIS 3.5) o SQLite · Google Gemini (`google-genai`) · Ollama local (`llama3.1:latest` por
defecto) · newspaper3k · plantillas Django + JavaScript sin framework · Docker Compose · gunicorn para
producción.

## Estado general

El proyecto tiene una base sólida y defensiva: validación estricta de las respuestas de IA, descargas
restringidas a El Territorio con protección anti-SSRF, transacciones con bloqueos, y unas **604 pruebas
Python** declaradas en 32 archivos. Esta auditoría no ejecutó esas pruebas. Su resultado actual queda
**NO VERIFICADO**.

El mayor riesgo actual no está en el diseño. Está en el **estado del repositorio local**:

1. **Integración sin commitear.** El árbol de trabajo mezcla la rama `feat/analisis-automatico-comentarios`
   con 107 archivos idénticos a `origin/main` y 19 archivos que difieren de ambas versiones. Las migraciones
   `0011_publicacion_texto_busqueda` a `0019` **no están en ningún commit de esta rama**, aunque
   `models.py` ya depende de ellas.
2. **`docker-compose.yml` local alterado.** Las variables `POSTGRES_*` ahora contienen valores literales
   precedidos por `$`, que Compose interpreta como variables, y una de ellas parece ser una credencial
   escrita en un archivo rastreado. Además, el servicio `ingesta` apunta a `DB_HOST: localhost`, que dentro
   de un contenedor no es la base de datos.
3. **Secretos en el historial.** El commit inicial `5ece768` incluía una `SECRET_KEY` `django-insecure` y
   una contraseña de PostgreSQL en el código, y el stash `stash@{1}` está descrito por su autor como
   "contiene clave".

## Recomendaciones prioritarias

1. Decidir cómo consolidar la integración local (commit en una rama nueva o rebase sobre `origin/main`)
   antes de seguir desarrollando, e incluir las migraciones sin commitear.
2. Restaurar en `docker-compose.yml` la forma `${DB_PASSWORD:?…}` de `origin/main` y `DB_HOST: db` para
   `ingesta`.
3. Rotar `SECRET_KEY`, la contraseña de PostgreSQL y `GEMINI_API_KEY` si alguna coincide con valores que
   estuvieron en el historial, el stash o los respaldos.
4. Ejecutar la suite completa en un PostgreSQL desechable y registrar el resultado.

El detalle y la lista completa están en [11_problemas_y_recomendaciones.md](11_problemas_y_recomendaciones.md).
