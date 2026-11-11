# Auditoría integral de TrendWatch Litoral

Documentación técnica generada a partir de la **inspección de solo lectura** del repositorio
`Trend-Watch-Litoral` el 05/11/2026. No se modificó código ni configuración, no se ejecutaron pruebas,
migraciones ni servicios, y no se consultó ninguna base de datos.

## Estado del repositorio auditado

| Dato | Valor |
|---|---|
| Raíz | `C:\Users\sofia\OneDrive\Escritorio\Proyecto\Trend-Watch-Litoral` |
| Rama | `feat/analisis-automatico-comentarios` |
| Commit (HEAD) | `bab5a3f` — "feat: automatizar analisis de sentimiento de comentarios" (Sof-0007, 27/10/2026) |
| Relación con `origin/main` (`e412f41`) | 2 commits por delante, 22 por detrás (merge-base `642084e`) |
| Árbol de trabajo | 50 archivos rastreados modificados y 82 sin seguimiento, ninguno commiteado |

**Importante:** la auditoría describe el **árbol de trabajo actual** (lo que hay en disco), no solo el
commit `HEAD`. Ese árbol es una integración local sin commitear entre la rama y `origin/main`
(ver [10_git_y_evolucion.md](10_git_y_evolucion.md)). Cuando una conclusión depende de archivos sin
commitear, se indica.

## Índice

| Archivo | Contenido |
|---|---|
| [01_resumen_ejecutivo.md](01_resumen_ejecutivo.md) | Qué es el sistema, qué hace hoy, estado y riesgos principales |
| [02_arquitectura_general.md](02_arquitectura_general.md) | Objetivos, arquitectura, stack tecnológico, flujo de datos, diagramas |
| [03_estructura_del_proyecto.md](03_estructura_del_proyecto.md) | Directorios, archivos, rutas URL, plantillas y JS |
| [04_modulos_y_funcionalidades.md](04_modulos_y_funcionalidades.md) | Cada módulo y funcionalidad, con su estado de implementación |
| [05_base_de_datos.md](05_base_de_datos.md) | Motor, modelos, relaciones, restricciones, migraciones |
| [06_ingesta_y_procesamiento.md](06_ingesta_y_procesamiento.md) | RSS, sitemaps, deduplicación, clasificación por categoría y departamento |
| [07_inteligencia_artificial_y_RAG.md](07_inteligencia_artificial_y_RAG.md) | Gemini, Ollama, sentimiento, y el estado real de RAG y embeddings |
| [08_seguridad_y_permisos.md](08_seguridad_y_permisos.md) | Autenticación, roles, permisos, exposición de datos, configuración sensible |
| [09_pruebas_y_calidad.md](09_pruebas_y_calidad.md) | Inventario de pruebas, cobertura, rendimiento, deuda técnica |
| [10_git_y_evolucion.md](10_git_y_evolucion.md) | Ramas, PR, autores, evolución, estado de integración |
| [11_problemas_y_recomendaciones.md](11_problemas_y_recomendaciones.md) | Problemas detectados priorizados, recomendaciones, informe de integridad |
| [12_glosario.md](12_glosario.md) | Glosario técnico y del dominio |

## Convenciones

- Las rutas son relativas a la raíz del repositorio.
- **NO VERIFICADO** marca lo que no se pudo confirmar sin ejecutar código o servicios.
- Ningún secreto se reproduce. Las credenciales se mencionan solo por su existencia y ubicación.
- Si la documentación del repositorio contradice el código, se prioriza el código y se señala la discrepancia.
