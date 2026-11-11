# 09 — Pruebas y calidad

**No se ejecutó ninguna prueba.** La suite usa la base de pruebas de Django y algunas clases exigen
PostgreSQL; ejecutarla requiere autorización y un entorno desechable. Todos los resultados son
**NO VERIFICADOS**. Las cifras siguientes son conteos estáticos de `def test_` y clases.

## 1. Inventario de pruebas Python (`app/core/`)

| Archivo | Métodos `test_` | Área |
|---|---|---|
| `tests.py` | 176 | Login, JWT y revocación, Gemini (integridad, transacciones), duplicados, concurrencia, comandos, roles, serializers, admin |
| `test_sentimiento_comentarios.py` | 47 | Modelo, servicio, comando y presentación del sentimiento de comentarios |
| `test_clasificacion.py` | 41 | Categoría por reglas, departamento por texto, lotes con IA, vínculos |
| `test_ingesta_historico.py` | 35 | Sitemaps, persistencia, deduplicación, errores individuales |
| `test_analisis_automatico.py` | 31 | Cola en segundo plano, publicación, edición, fallos y recuperación |
| `test_gemini_errores.py` | 29 | Modelo configurado, reintentos, saneamiento de mensajes (no existe en `origin/main`) |
| `test_gestion_administradores.py` | 22 | Alta de administradores, seguridad, concurrencia |
| `test_perfil.py` | 22 | Perfil, credenciales, bloqueo en PostgreSQL |
| `test_buscador.py` | 19 | Búsqueda |
| `test_fase2_3.py` | 17 | Territorio, identidad de URL, Gemini, límites |
| `test_identidad.py` | 16 | Colisiones de identidad, concurrencia en PostgreSQL |
| `test_sugerencias.py` | 15 | Autocompletado |
| `test_fechas.py` | 14 | Fecha efectiva y precisión |
| `test_departamentos_ia.py` | 12 | `revisar_departamentos` y validación de evidencia |
| `test_busqueda_html.py` | 11 | Resaltado y página HTML |
| `test_categorias_compat.py`, `test_comentarios.py` | 10 + 10 | Lectura compatible de categorías, comentarios |
| `test_new_dashboard.py`, `test_recuperar_imagenes.py` | 9 + 9 | Dashboard, recuperación de fotos |
| `test_portada_regional.py`, `test_texto_busqueda.py` | 8 + 8 | Portada y moderación, columnas generadas y migración |
| `test_auth_views.py`, `test_valoraciones.py` | 7 + 7 | Modal de autenticación, valoraciones |
| `test_publicacion_imagen.py` | 6 | Validación de imágenes |
| `test_cotizaciones.py`, `test_localidades.py` | 5 + 5 | DolarAPI (simulada), catálogo territorial |
| `test_integracion_pr24.py` | 4 | Integración PR24 |
| `test_ingesta_validacion.py`, `test_publicaciones_paginacion.py` | 3 + 3 | newspaper local, paginación |
| `test_dashboard_localidades.py`, `test_indicadores_inicio.py`, `test_navegacion_admin.py` | 1 + 1 + 1 | Regresiones puntuales |
| **Total** | **604** en 32 archivos | |

Otras pruebas:

- `app/core/test_auth_flow.js` — `node --test` para `auth-flow.js` (DOM simulado).
- `tools/fase*/`, `tools/buscador/`, `tools/gestion_administradores/` — arneses y pruebas por fase (Python,
  Node y shell), con README que documentan su alcance. `tools/fase1_1/README.md` advierte: "No ejecutar el
  arnés PostgreSQL hasta completar la nueva revisión".
- `test_ingesta.py` (raíz) — prueba manual con `pytest` y `requests` contra un servidor en marcha.
  **`pytest` y `requests` no están en `requirements.txt`**, y la prueba crea datos.

## 2. Tipo de pruebas

- **Unitarias:** reglas de clasificación, validación de respuestas de IA, fechas, localidades, saneamiento.
- **Integración con BD:** la mayoría usa `TestCase` de Django y los servicios externos (El Territorio,
  Gemini, Ollama, DolarAPI) están **simulados con mocks** (24 archivos usan `mock` o `patch`).
- **Funcionales HTTP:** `Client` de Django sobre vistas y API.
- **Dependientes de PostgreSQL:** concurrencia, advisory locks e introspección de restricciones
  (`IdentidadConcurrentePostgreSQLTests`, `PerfilBloqueoPostgreSQLTests`, `AltaConcurrenteTests`, y
  duplicados y concurrencia en `tests.py`). El README indica que **6 fallan con SQLite**.
- **Sin pruebas contra servicios reales:** ninguna prueba automatizada llama a Gemini, Ollama ni El
  Territorio reales.

## 3. Cobertura

- No hay configuración de cobertura (`.coveragerc`, `coverage` en dependencias) ni umbral. El porcentaje
  queda **NO VERIFICADO**.
- **Módulos sin un archivo de prueba propio identificado** (pueden tener cobertura indirecta en
  `tests.py`): `views_valoraciones` (cubierto por `test_valoraciones`), `services/moderacion_comentarios`
  (cubierto en parte por `test_portada_regional` y `ModeracionYAgendaTests`), `services/relevancia`
  (portada), `services/indicadores`, el comando `ingestar_recientes` (lo menciona
  `test_portada_regional.py`; que se cubra su bucle completo queda **NO VERIFICADO**), `medir_buscador`,
  y JavaScript fuera de `auth-flow.js`.

## 4. Errores conocidos y documentados en el repositorio

- 6 pruebas fallan con SQLite (README).
- `docs/trazabilidad-requisitos.md` (corte del 15/10) no tiene ningún requisito en estado "Verificado".
- `tools/fase1_1/README.md`: arnés PostgreSQL pendiente de revisión de seguridad.

## 5. Dependencias entre pruebas

- Las pruebas con `IngestaSimuladaMixin` y `BaseComentarios` comparten fixtures por herencia.
- Las de `analisis_automatico` reemplazan `_enviar_a_segundo_plano` para evitar hilos reales (docstring).
- Las pruebas de `gemini_cliente` dependen del objeto global `gemini_cliente`, instanciado al importar.

## 6. Rendimiento (análisis estático)

| # | Punto | Evidencia | Impacto |
|---|---|---|---|
| R1 | `procesar_pendientes` duerme **12 s por publicación**. Con lote de 10 desde `/procesar-ia/` o `/api/publicaciones/ingestar/…`, la petición dura más de 108 s, más las llamadas | `gemini_cliente.py`, línea ~378 | Supera el `--timeout=60` de gunicorn en producción; el worker se reinicia a mitad del lote |
| R2 | `listar_publicaciones`: 1 consulta de `Sentimiento` por publicación (hasta 150) | `views.py`, línea 594 | N+1 consultas |
| R3 | `publicaciones_localidad`: trae todos los nombres de `Locacion` a Python y devuelve **todas** las noticias del departamento sin paginación | `views.py`, líneas 183–205 | Crece con la base |
| R4 | `publicaciones` y `dashboard`: recorren en Python todas las ubicaciones distintas en cada petición | `views.py`, `views_dashboard.py` | Moderado |
| R5 | La búsqueda usa `LIKE '%term%'` sobre columnas generadas, sin índice trigram ni FTS | `buscador.py`; `medir_buscador` mide 500 y 5000 noticias | Escaneo secuencial; aceptable a baja escala |
| R6 | `candidatos_con_hash_desactualizado` recalcula SHA-256 en Python sobre todos los comentarios procesados | `sentimiento_comentarios.py` | Lineal en comentarios; corre solo en el comando |
| R7 | Portada: 12 consultas de destacadas (una por categoría, hasta 300 candidatas cada una) y orden en Python | `relevancia.py` | Moderado en cada visita, sin caché |

## 7. Deuda técnica

- **Integración local sin commitear** y migraciones fuera del control de versiones (ver
  [10](10_git_y_evolucion.md)).
- **Código muerto o legacy:** `scrapers/noticias.py`, `gemini_cliente.disparar_ingesta`, modelos `Role`,
  `User`, `VotoPublicacion`, `Auditoria` y `UserAuditoria`, plantillas `landing.html`, `litoral.html` y
  `login.html`, y `fixtures/roles.json`.
- **Vista dentro de un servicio:** `gemini_cliente.py` importa `JsonResponse` y decoradores de vistas.
- **Efecto al importar:** `GeminiCliente()` se crea al importar el módulo y lee la configuración en ese
  momento.
- **Sin linter ni formateador** configurado (lo dice `AGENTS.md`).
- **Mensajes desactualizados:** `run_pipeline` dice "Gemini 1.5 Pro" y el modelo por defecto es
  `gemini-3.8-flash`. La nota de indicadores dice "exclusivo de superusuarios".
- **Constantes rígidas:** `FiltrosPublicaciones.clean_fecha` rechaza fechas anteriores a 2026-01-01. Las
  fuentes RSS están fijas en el código.
- **Léxico de sentimiento mínimo** y confianza constante de 0,4 (ver [07 §5](07_inteligencia_artificial_y_RAG.md)).
- **Duplicación consciente:** la lista de expresiones bloqueadas está copiada en la migración `0015`
  (correcto para migraciones, pero hay que mantener ambas).
- **Archivos residuales** en la raíz: `diff_gemini.txt`, `grep.exe.stackdump`.
- **Variables de entorno no documentadas** en `.env.example`: `OLLAMA_BASE_URL`, `OLLAMA_MODELO_CHAT`,
  `OLLAMA_TIMEOUT`, `SENTIMIENTO_COMENTARIOS_AUTOMATICO`, `SENTIMIENTO_COMENTARIOS_METODO`. A la inversa,
  `.env.example` declara `ELTERRITORIO_RSS_URL` y `TIME_ZONE`, que **el código no lee** (la zona horaria
  está fija en `settings.py`).
- **Documentación desactualizada:** la tabla de rutas del README, CAT-01 (4 categorías frente a 12) y la
  matriz de trazabilidad (corte del 15/10, anterior a buscador, ingesta periódica y tendencias).

## 8. Cómo ejecutar las pruebas (requiere autorización)

Según el README y `AGENTS.md`, en un PostgreSQL **aislado y desechable**:

```bash
docker compose exec web python manage.py test core
node --test app/core/test_auth_flow.js
```

No usar la base compartida ni la de desarrollo con datos: las pruebas de concurrencia escriben en la base.
