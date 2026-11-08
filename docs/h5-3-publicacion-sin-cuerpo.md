# H5.3: publicaciones RSS sin cuerpo completo

## Contrato

`Publicacion.contenido_completo` distingue un artículo cuyo cuerpo fue extraído
de una ficha que conserva sólo metadatos y enlace. El valor predeterminado es
`True`: las filas históricas no se reclasifican ni se reescriben. En H5.3 no se
ingestan feeds ni se crea una ruta de persistencia RSS de metadatos.

Las altas completas requieren texto no vacío; las fichas se guardan con el
indicador explícito en `False` y `contenido=''`. La restricción de base impide
que una fila marcada sin cuerpo contenga texto. No se añadió una restricción
inversa que pudiera rechazar filas históricas preexistentes con cuerpo vacío.
El pipeline H2/H3 que exige cuerpo suficiente permanece sin cambios.

## Exclusiones de análisis

Las fichas no generan etiquetas automáticas, clasificación por reglas o Gemini,
revisión territorial ni análisis de sentimiento. Los selectores las descartan
antes de los límites; los puntos de entrada directos también las revalidan.
Las tareas de recuperación de imagen no descargan páginas para estas filas.
El Territorio y los artículos completos mantienen su flujo habitual.

## Consecuencias para H5.4 y H5.5

- H5.4 deberá crear fichas desde metadatos autorizados, con fecha sólo si el RSS
  ofrece una fecha interpretable, URL original validada y sin cuerpo, resumen,
  imagen ni análisis inventados. La idempotencia debe reutilizar alias H3.1 y
  conservar separada la política de acceso por medio.
- H5.5 deberá presentar claramente que la ficha enlaza al medio original; el
  detalle no debe aparentar que TrendWatch aloja el artículo completo. Debe
  conservar búsqueda/listado y omitir controles o indicadores que impliquen
  análisis inexistentes. La política de retención y de visualización de títulos
  debe aprobarse por fuente antes de habilitarla.
- Esta etapa no resuelve permisos de automatización, almacenamiento o exhibición
  de titulares para ninguno de los medios, ni activa fuentes o Gemini.

## Validación

La migración `0023_publicacion_contenido_completo` depende de `0022` y sólo
agrega el booleano con default compatible, permite el campo de texto vacío y
añade la restricción para filas declaradas sin cuerpo. No incluye operaciones
de datos. La verificación de aplicación y conservación histórica debe hacerse
en PostgreSQL/PostGIS efímero, nunca en la base habitual.
