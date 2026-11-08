# H5.5 — Presentación de fichas RSS

Las publicaciones con `contenido_completo=False` se muestran como fichas enlazadas, sin cuerpo, extracto, imagen, categorías, localidades ni etiquetas inventadas. La portada las reúne en una sección propia; el detalle conserva título, fuente, fecha disponible y enlace original. El buscador consulta título, fuente y texto realmente almacenado, y deja vacío el extracto de una ficha.

## Significado de indicadores

- **Publicaciones** y los gráficos de evolución, fuente, categoría y departamento abarcan todos los registros. Las fichas sin asociaciones aparecen sin categoría/departamento, sin que eso implique un valor inventado.
- **Artículos completos**, **análisis**, **pendientes** e **inconsistentes** se calculan solo para publicaciones con `contenido_completo=True` y texto no vacío. Las fichas RSS no consumen el cupo de pendientes de IA.
- **Fichas RSS** se informa por separado. Los registros históricos declarados completos pero sin texto se reflejan como `sin_cuerpo_sin_ficha`, no se reinterpretan como fichas ni se modifican.
- Las selecciones heurísticas por título/cuerpo excluyen las fichas. Los rankings de tendencias y valoraciones basados en participación real de lectores pueden incluirlas, con una etiqueta explícita de ficha.

No se agregan migraciones ni se cambia el flujo persistente H5.4. Esta etapa no autoriza reutilización de contenido ni activa fuentes o Gemini. La incorporación de permisos y políticas por medio queda pendiente de H5.6; la adaptación adicional de estadísticas/rankings según decisiones de producto puede abordarse en H5.8.
