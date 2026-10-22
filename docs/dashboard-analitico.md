# Dashboard y Publicaciones

`/publicaciones/` conserva el CRUD y los filtros de gestión, protegido por el conjunto de permisos existente. `/dashboard/` pasa a ser un panel analítico exclusivo de `is_superuser`, con control en servidor; no alcanza con ser staff o pertenecer al grupo Administrador.

El Dashboard consulta todas las publicaciones coincidentes, sin límite de 100, mediante filtros GET por fechas inclusivas, categoría asociada, fuente y departamento. Usa fecha de publicación o, si falta, captura, interpretadas en Argentina. Las relaciones múltiples no duplican publicaciones. Categorías y departamentos pueden sumar más que el total porque una publicación puede tener varias asociaciones.

Los KPIs distinguen: total; un único sentimiento con polaridad y confianza dentro de rango; sin sentimiento (pendiente); múltiples sentimientos o datos fuera de rango (a revisar). No se confunde ausencia con neutralidad ni se toma `procesado_ia` como prueba suficiente de análisis. La distribución usa el signo de la polaridad almacenada y no incorpora votos de lectores.

La evolución agrupa por día; para intervalos mayores de 120 días agrupa por mes. Se muestran los períodos con registros y una tabla accesible con los valores exactos. Las otras visualizaciones representan categorías, fuentes, departamentos y sentimiento con barras y cantidades reales.

No hay procesamiento IA, nuevas métricas de relevancia ni alertas automáticas. La indicación de pendientes es informativa. Una consulta no modifica la base. Sin resultados o con filtros inválidos se muestran estados explícitos; las fechas o selecciones inválidas responden HTTP 400.

No requiere migraciones ni dependencias nuevas. Pruebas: `python manage.py test core.test_new_dashboard`.
