# Dashboard y Publicaciones

`/publicaciones/` conserva el CRUD y los filtros de gestión. `/dashboard/` usa el mismo conjunto `PERMISOS_PANEL` (ver, agregar, cambiar y eliminar publicaciones), con control en servidor. El rol Administrador configurado tiene esos permisos; `is_staff` por sí solo no alcanza. La gestión de administradores y su alcance se describen en [gestion-administradores.md](gestion-administradores.md).

El Dashboard consulta todas las publicaciones coincidentes, sin límite de 100, mediante filtros GET por fechas inclusivas, categoría asociada, fuente y departamento. Usa fecha de publicación o, si falta, captura, interpretadas en Argentina. Las relaciones múltiples no duplican publicaciones. Categorías y departamentos pueden sumar más que el total porque una publicación puede tener varias asociaciones.

Los KPIs distinguen: total; un único sentimiento con polaridad y confianza dentro de rango; sin sentimiento (pendiente); múltiples sentimientos o datos fuera de rango (a revisar). No se confunde ausencia con neutralidad ni se toma `procesado_ia` como prueba suficiente de análisis. La distribución usa el signo de la polaridad almacenada y no incorpora votos de lectores.

La evolución agrupa por día; para intervalos mayores de 120 días agrupa por mes. La distancia horizontal es proporcional a días transcurridos o al índice absoluto de mes. Los períodos sin registros conservan su espacio sin agregar puntos ni ceros. Se muestran los períodos con registros y una tabla accesible con los valores exactos. Las otras visualizaciones representan categorías, fuentes, departamentos y sentimiento con barras y cantidades reales.

No hay procesamiento IA, nuevas métricas de relevancia ni alertas automáticas. La indicación de pendientes es informativa. Una consulta no modifica la base. Sin resultados o con filtros inválidos se muestran estados explícitos; las fechas o selecciones inválidas responden HTTP 400.

No requiere migraciones ni dependencias nuevas. Pruebas: `python manage.py test core.test_new_dashboard`.

## Inicio y navegación

La navbar de administradores sigue el orden Inicio / Publicaciones / Categorías / Dashboard. El acceso usa permisos efectivos, sin exigir superusuario. Los visitantes y lectores comunes no reciben accesos administrativos.

Inicio muestra a quienes tienen `PERMISOS_PANEL` tres indicadores antes de Salud: publicaciones, con análisis y pendientes. Usa la misma función de conteo que Dashboard, sobre toda la base y sin disparar IA. Si hay inconsistencias se informa su cantidad para que los tres números no se interpreten como una partición completa. El backend no calcula ni envía esos indicadores a otras cuentas. Tendencias y Cotizaciones permanecen en el lateral.

Pruebas adicionales: `core.test_navegacion_admin` y `core.test_indicadores_inicio`.
