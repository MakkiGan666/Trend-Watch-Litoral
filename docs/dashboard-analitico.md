# Dashboard y Publicaciones

`/publicaciones/` conserva el CRUD y los filtros de gestión para el rol Administrador. `/dashboard/` queda reservado a superusuarios, con control en servidor. La gestión de administradores y su alcance se describen en [gestion-administradores.md](gestion-administradores.md).

El Dashboard consulta todas las publicaciones coincidentes, sin límite de 100, mediante filtros GET por fechas inclusivas, categoría asociada, fuente y departamento. Usa fecha de publicación o, si falta, captura, interpretadas en Argentina. Las relaciones múltiples no duplican publicaciones. Categorías y departamentos pueden sumar más que el total porque una publicación puede tener varias asociaciones.

Los KPIs distinguen: total; un único sentimiento con polaridad y confianza dentro de rango; sin sentimiento (pendiente); múltiples sentimientos o datos fuera de rango (a revisar). No se confunde ausencia con neutralidad ni se toma `procesado_ia` como prueba suficiente de análisis. La distribución usa el signo de la polaridad almacenada y no incorpora votos de lectores.

La evolución agrupa por día; para intervalos mayores de 120 días agrupa por mes. La distancia horizontal es proporcional a días transcurridos o al índice absoluto de mes. Los períodos sin registros conservan su espacio sin agregar puntos ni ceros. Se muestran los períodos con registros y una tabla accesible con los valores exactos. Las otras visualizaciones representan categorías, fuentes, departamentos y sentimiento con barras y cantidades reales.

No hay procesamiento IA, nuevas métricas de relevancia ni alertas automáticas. La indicación de pendientes es informativa. Una consulta no modifica la base. Sin resultados o con filtros inválidos se muestran estados explícitos; las fechas o selecciones inválidas responden HTTP 400.

No requiere migraciones ni dependencias nuevas. Pruebas: `python manage.py test core.test_new_dashboard`.

## Inicio y navegación

La navbar muestra Inicio / Publicaciones / Categorías / Dashboard / Administradores según el usuario. Dashboard sólo aparece para superusuarios; el alta controlada de administradores está disponible para el rol autorizado. Los visitantes y lectores comunes no reciben accesos administrativos.

Inicio muestra sólo a superusuarios tres indicadores antes de las noticias regionales: publicaciones, con análisis y pendientes. Usa la misma función de conteo que Dashboard, sobre toda la base y sin disparar IA. Si hay inconsistencias se informa su cantidad para que los tres números no se interpreten como una partición completa. El backend no calcula ni envía esos indicadores a otras cuentas. Tendencias y Cotizaciones permanecen en el lateral.

Pruebas adicionales: `core.test_navegacion_admin` y `core.test_indicadores_inicio`.

## Observatorio de la agenda mediática (portada y panel de observación)

TrendWatch Litoral se presenta como observatorio de la agenda mediática de Misiones, con cuatro dimensiones: territorio (17 departamentos), temática (categorías), evolución temporal y análisis de contenido (tono de publicaciones y de comentarios, por separado). Los cálculos viven en `core/services/observatorio.py` y los comparten la portada y el Dashboard.

**Portada (pública).** Antes de las noticias por categoría muestra: presentación del observatorio; publicaciones registradas; publicaciones de los últimos 30 días con variación frente a los 30 previos; departamentos con cobertura (x/17); temas con presencia; temas con mayor presencia y su cambio; publicaciones por semana (12 semanas); departamentos con más cobertura (enlazan a `/localidad/<slug>/`). El período termina en la última publicación registrada hasta hoy (las fechas futuras no lo anclan). No expone el estado del análisis IA: ese bloque sigue siendo exclusivo de quien tiene acceso al panel, igual que el enlace «Abrir panel de análisis».

**Panel (`/dashboard/`, mismos permisos que antes).** Filtros: búsqueda de texto (mismo criterio que Publicaciones: todas las palabras en título, contenido o fuente), período rápido (7/30/90/365 días hasta hoy) o rango Desde/Hasta (no combinables), categoría, departamento y fuente. Secciones:

- Evolución: serie temporal existente; comparación del rango elegido (o, sin rango completo, los últimos 30 días con datos) contra el período anterior de igual duración; temas en aumento y en descenso; matriz tema × mes (últimos 6 meses con registros, 6 temas principales).
- Territorio: ranking de los 17 departamentos (incluye los que tienen 0), mayor y menor cobertura, publicaciones sin departamento identificado y foco del departamento elegido con sus temas. El ranking ignora el filtro de departamento para permitir comparar; el resto de los filtros se aplica.
- Temas y fuentes: barras enlazadas que filtran el panel o abren `/publicaciones/` con filtros equivalentes (`localidad`, `categoria`, `q`).
- Tono: sentimiento de publicaciones (modelo `Sentimiento`) y de comentarios publicados (`SentimientoComentario` vigente) en tarjetas separadas, con aviso de que no representan la opinión de la población.
- Participación de lectores: sin cambios de cálculo.

**Limitaciones conocidas.**

- No hay mapa: `Locacion` no tiene registros con coordenadas en la base actual, por eso se usa un ranking. No se inventan coordenadas.
- Una parte importante de las publicaciones no tiene departamento identificado (noticias provinciales, nacionales o sin evidencia) y otra parte no tiene categoría asociada; ambas se informan explícitamente y no se reparten.
- En la base actual no hay análisis de sentimiento de publicaciones; el panel lo indica con un estado vacío hasta que se procesen.
- `/publicaciones/` sólo filtra por un día, no por rango: los enlaces desde el panel trasladan búsqueda, departamento y categoría, pero no el período.
- La comparación de períodos cuenta publicaciones registradas; un aumento puede reflejar más ingesta y no sólo más cobertura de los medios.

Pruebas: `python manage.py test core.test_observatorio`.
