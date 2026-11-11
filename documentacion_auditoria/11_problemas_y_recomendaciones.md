# 11 — Problemas detectados, recomendaciones e informe de integridad

Gravedad: **Crítica** (bloquea o arriesga datos y secretos) · **Alta** · **Media** · **Baja**.

## 1. Problemas detectados

| ID | Problema | Evidencia | Gravedad |
|---|---|---|---|
| P1 | **Migraciones fuera de Git.** `models.py` del árbol requiere `0011_publicacion_texto_busqueda` a `0019`, que no están en ningún commit de esta rama. Commitear solo `models.py` o cambiar de rama sin ellas deja el esquema inconsistente | `git status`; [05 §4](05_base_de_datos.md) | Crítica |
| P2 | **Integración manual sin commitear** de `origin/main` sobre la rama (107 archivos idénticos a main y 21 propios) | [10 §2](10_git_y_evolucion.md) | Crítica |
| P3 | **`docker-compose.yml` local:** `POSTGRES_DB`, `POSTGRES_USER` y `POSTGRES_PASSWORD` usan valores literales con `$`, que Compose interpreta como variables inexistentes (cadena vacía, con aviso). Un volumen nuevo no se inicializaría sin contraseña; uno existente conserva la anterior. Además, puede dejar una credencial en un archivo rastreado | `docker-compose.yml`, líneas 8–10; `origin/main` usa `${DB_*}` | Crítica |
| P4 | **Servicio `ingesta` con `DB_HOST: localhost`** en el archivo local. Dentro del contenedor, `localhost` es el propio contenedor y no `db`, así que la ingesta periódica no puede conectarse | `docker-compose.yml`, línea 52 (`origin/main`: `db`) | Alta |
| P5 | **Secretos en el historial** (commit `5ece768`) y en un stash local | [08 §6](08_seguridad_y_permisos.md), S2 y S3 | Alta |
| P6 | **Peticiones HTTP que superan el timeout:** `procesar_pendientes` duerme 12 s por noticia y se llama con lote de 10 desde vistas web y API (más de 108 s, con gunicorn a 60 s) | `gemini_cliente.py:378`; `views.procesar_ia`, `views.disparar_ingesta` | Alta |
| P7 | **Hilo de análisis en memoria:** cola perdida al reiniciar, una cola por worker y sin respaldo programado (el comando de respaldo es manual) | `analisis_automatico.py` | Media |
| P8 | **Sin rate limiting** en login, registro y JWT | [08 §1](08_seguridad_y_permisos.md) | Media |
| P9 | **Confianza léxica constante de 0,4** y léxico mínimo (15 términos, subcadenas, sin negaciones) | `sentimiento.py`; [07 §5](07_inteligencia_artificial_y_RAG.md) | Media |
| P10 | **N+1 consultas** en `/api/publicaciones/` y **sin paginación** en `/api/localidades/<slug>/publicaciones/` | `views.py:594`, `views.py:183–205` | Media |
| P11 | **Unicidad no garantizada en la base** para `Sentimiento` por publicación y `Categoria.nombre_categoria` | `models.py`; [05 §5](05_base_de_datos.md) | Media |
| P12 | **Scraper legacy** `scrapers/noticias.py` usa el ID de la URL como clave primaria (`get_or_create(id_publicacion_api=…)`), que puede colisionar con IDs autoincrementales | `scrapers/noticias.py`, líneas 58–70 | Media (solo si se usa) |
| P13 | **`Sentimiento` no registra método ni modelo**: no se distingue el léxico de Gemini | `models.Sentimiento` | Media |
| P14 | **Publicaciones manuales nunca pasan por Gemini** (el léxico marca `procesado_ia=True`) y no obtienen `Locacion` | `views._analizar_y_guardar_sentimiento` | Baja (decisión de diseño no documentada) |
| P15 | **`logout` por GET** | `views.logout_view` | Baja |
| P16 | **Documentación desactualizada o contradictoria:** rutas del README, CAT-01 (4 categorías frente a 12), nota de indicadores "solo superusuarios", `run_pipeline` "Gemini 1.5 Pro", `.env.example` incompleto y con variables que no se leen | [03 §4](03_estructura_del_proyecto.md), [09 §7](09_pruebas_y_calidad.md) | Baja |
| P17 | **Código muerto:** plantillas sin uso, modelos legacy, vista duplicada en `gemini_cliente.py`, dependencias `pandas`, `scipy` y `feedparser` | [04 §10](04_modulos_y_funcionalidades.md) | Baja |
| P18 | **Archivos residuales** `diff_gemini.txt` y `grep.exe.stackdump` en la raíz | `git status` | Baja |
| P19 | **`test_ingesta.py`** necesita `pytest` y `requests` (no declarados) y crea datos | raíz | Baja |
| P20 | **Worktrees en un directorio temporal** de una sesión anterior | `git worktree list` | Baja |
| P21 | **Nombre de rama engañoso:** `feat/llm-rag-interacciones` no contiene RAG | [07 §7](07_inteligencia_artificial_y_RAG.md) | Baja |
| P22 | **Requisitos sin implementar:** resúmenes (2.0), insights (2.1), reportes (3.1.3), alertas (3.1.4), emergentes (4.0), comparación (4.1), predicción (4.2) e ingesta de redes sociales (1.1) | `docs/trazabilidad-requisitos.md`, código | Alcance funcional |

> **Nota sobre el error de `psql`** (contexto de la consulta previa de la usuaria, no forma parte del
> código): `psql` sin parámetros se conecta a `localhost:5432` con el usuario del sistema operativo
> (`sofia`). La base del Compose se publica en `127.0.0.1:5433` y su usuario por defecto es `postgres`. Ese
> error de autenticación es coherente con haber contactado otro servidor (por ejemplo, un PostgreSQL
> instalado en Windows en el 5432) o con un usuario inexistente, y P3 puede agravarlo. **NO VERIFICADO**:
> no se inspeccionaron puertos ni servicios.

## 2. Deuda técnica (resumen)

Detalle en [09 §7](09_pruebas_y_calidad.md): integración sin commitear, código legacy, una vista dentro de
un servicio, un cliente instanciado al importar, sin linter, constantes rígidas (fecha mínima 2026, fuentes
en el código), léxico mínimo, documentación desactualizada y variables de entorno sin documentar.

## 3. Recomendaciones de mejora

### Inmediatas (antes de seguir desarrollando)

1. **Respaldar y consolidar la integración.** Crear una rama nueva desde el estado actual y commitear todo,
   **incluidas las migraciones 0011–0019**. Alternativa: rehacer la integración con un `merge` real de
   `origin/main` sobre `feat/analisis-automatico-comentarios`. Cualquiera de las dos opciones debe
   decidirla el equipo.
2. **Restaurar `docker-compose.yml`** con la interpolación `${DB_NAME:-db}`, `${DB_USER:-postgres}` y
   `${DB_PASSWORD:?…}` de `origin/main`, y con `DB_HOST: db` para `ingesta`. Nunca commitear valores
   literales.
3. **Rotar secretos** que puedan coincidir con el commit inicial, el stash o los respaldos. Borrar o
   archivar con acceso restringido el stash "contiene clave" y el volcado de base.
4. **Ejecutar la suite** (`manage.py test core`) y `makemigrations --check --dry-run` en un PostgreSQL
   desechable, y registrar los resultados.

### Corto plazo

5. Sacar de la petición HTTP el procesamiento de Gemini (con un comando programado o una cola) o eliminar
   el `sleep(12)` de la ruta web; alinear el timeout de gunicorn.
6. Programar `analizar_sentimiento_comentarios` como respaldo periódico (por ejemplo, con un segundo bucle
   como `ingestar_recientes`).
7. Agregar throttling a la autenticación y hacer que `/logout/` acepte solo POST.
8. Resolver el N+1 de `listar_publicaciones` con `prefetch_related('sentimiento_set')` y paginar la API por
   localidad.
9. Agregar `UniqueConstraint` a `Sentimiento(id_publicacion_api)` y `Categoria(nombre_categoria)` después
   de depurar los duplicados existentes.
10. Agregar `metodo` y `modelo` a `Sentimiento`.

### Mediano plazo

11. Reemplazar el léxico por un modelo de sentimiento real o usar Ollama también para noticias, con una
    confianza significativa.
12. Retirar el código legacy, las plantillas sin uso y las dependencias sin uso.
13. Actualizar el README (rutas, variables de Ollama), alinear o archivar CAT-01 y actualizar la matriz de
    trazabilidad.
14. Agregar un linter o formateador (por ejemplo, `ruff`) y medición de cobertura.
15. Si se busca RAG o búsqueda semántica: definir el caso de uso, elegir embeddings (Gemini u Ollama) y
    almacenamiento (`pgvector`, que es compatible con la imagen PostgreSQL), y documentarlo antes de
    implementarlo.
16. Considerar un índice trigram (`pg_trgm`) o búsqueda de texto completo (FTS) para la búsqueda si la base
    crece.

## 4. Informe final de integridad

| Verificación | Inicial | Final |
|---|---|---|
| Rama | `feat/analisis-automatico-comentarios` | `feat/analisis-automatico-comentarios` |
| Commit | `bab5a3f111ec0860ba8e23f010676a6c8121c4b8` | `bab5a3f111ec0860ba8e23f010676a6c8121c4b8` |
| Estado Git | 50 modificados, 82 sin seguimiento | Idéntico, más los archivos nuevos de `documentacion_auditoria/` |
| Stashes / worktrees | 2 / 5 | 2 / 5 |
| Archivos originales (504, sin `.git` ni `venv`) | Instantánea SHA-1 | **Idénticos**: comparación SHA-1 sin diferencias |

- **Archivos originales modificados:** ninguno.
- **Archivos originales eliminados:** ninguno.
- **Archivos nuevos creados:** 13, todos dentro de `documentacion_auditoria/`: `README.md` y del
  `01_resumen_ejecutivo.md` al `12_glosario.md`. El directorio no existía antes de la auditoría.
- **Archivos temporales:** las instantáneas de verificación se guardaron fuera del repositorio, en el
  directorio temporal de la sesión.

**Operaciones no realizadas (por las reglas de protección):**

- No se ejecutaron pruebas, migraciones, `manage.py check`, `makemigrations --check`, `pip-audit`, Docker
  ni servicios.
- No se consultó ninguna base de datos ni se abrieron `.env` (solo los nombres de las variables), los
  stashes, los respaldos, `Informe_Estado_TrendWatch.pdf` ni el volcado.
- No se accedió a la red (sin `git fetch`, ni GitHub, ni Gemini, Ollama o El Territorio).

**Limitaciones de la auditoría:**

- El análisis es estático. El comportamiento en ejecución, los resultados de las pruebas, el grafo de
  migraciones y los datos reales quedan **NO VERIFICADOS**.
- Las referencias remotas dependen del último fetch local.
- Las plantillas, el CSS y el JavaScript se revisaron por estructura y puntos de integración, no línea por
  línea.
- La autoría personal se informa solo como identidades de commit de Git. Los cambios sin commitear no
  tienen autor verificable.

**Condición de finalización:** se generó la documentación técnica sobre el estado real del árbol de trabajo
y se preservaron todos los archivos originales.
