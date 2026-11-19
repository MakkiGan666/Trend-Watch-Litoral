# Detección conservadora de duplicados editoriales

El detector es una herramienta de diagnóstico. No fusiona, borra, oculta ni
modifica publicaciones; tampoco interviene en búsqueda, dashboard o ingestas.

## Evidencia evaluada

La auditoría de 2026-11-19 registró 94 grupos de títulos exactos de al menos
35 caracteres en `El Territorio (Archivo)` (95 filas adicionales), y 98 grupos
al normalizar caja y espacios (99 filas adicionales). También señaló un grupo
de URL exacta de tres filas de prueba (IDs 20–22), cuatro títulos compartidos
entre secciones de El Territorio, y 30 fichas RSS sin grupos de títulos largos.
Esas coincidencias no prueban por sí mismas que se trate de la misma noticia.

## Criterios reproducibles

- Normalización textual: Unicode NFKD, casefold, eliminación de diacríticos,
  puntuación separadora y espacios repetidos.
- El límite del comando `--titulo-minimo` se aplica a la longitud original del
  título para reproducir cortes de auditoría sin perder títulos puntuados.
- Fuente: las etiquetas de secciones conocidas de El Territorio se agrupan
  bajo ese medio; otras fuentes mantienen su identidad normalizada.
- URL: host y esquema se normalizan, se descartan `www`, fragmento y parámetros
  de seguimiento conocidos. Se conserva el path y la query funcional. No se
  consultan redirects ni canonical tags.
- Fecha: sólo `fecha_publicacion`; la fecha de captura nunca la reemplaza.
- Cuerpo: sólo se compara cuando ambos registros indican `contenido_completo`
  y tienen al menos 300 caracteres normalizados.
- Confirmado: misma URL canonicalizada dentro de la misma fuente; o misma
  fuente, fecha a un día, título relacionado y similitud de cuerpo >= 0,94.
- Probable: misma fuente, fecha a dos días, similitud de título >= 0,80 y
  similitud de cuerpo >= 0,78.
- Ficha incompleta coincidente: `DATOS_INSUFICIENTES`, nunca duplicado por
  título/fecha solamente.
- Fuentes diferentes: `COBERTURA_MULTIMEDIO` cuando título y fecha concuerdan;
  la procedencia se preserva y no se fusiona. Una coincidencia nominal más
  débil queda separada de una duplicación.
- Título/fecha cercanos con cuerpos disponibles que no concuerdan se reportan
  como `TITULO_COINCIDENTE_DISTINTO_CONTENIDO`.
- Otras coincidencias nominales sin evidencia suficiente se conservan en la
  salida como `TITULO_REPETIDO_NO_CONFIRMADO`, para que no desaparezcan del
  dry-run ni se presenten como duplicados.

Las similitudes son reglas de triage deterministas, no una verdad editorial.
La canonicalización no conoce IDs editoriales del path y puede dejar escapar
alias que requieren evidencia adicional. La normalización de `www` y esquema
puede unir URLs técnicamente distintas; por eso sólo se considera confirmación
URL dentro de la misma fuente y debe revisarse en el reporte.

## Ejecución

En PostgreSQL, usar únicamente:

```sh
python manage.py auditar_duplicados_editoriales --dry-run --fuente "El Territorio" --titulo-minimo 35
```

Para reproducir exactamente el corte del informe original (la etiqueta
`El Territorio (Archivo)`), agregar `--etiqueta-fuente "El Territorio (Archivo)"`.

El comando exige `--dry-run`, PostgreSQL y abre una transacción `READ ONLY`.
Emite JSON por stdout, sin guardar el resultado ni cuerpos editoriales. Los
resultados son pares, por lo que un grupo de tres puede aparecer como tres pares.

## Integración futura

La persistencia actual conserva idempotencia por URL/alias dentro de la fuente.
Este detector complementa esa identidad, pero en esta fase no cambia su
comportamiento. Antes de aplicar agrupación en buscador o persistencia se
requiere revisar candidatos y definir cómo presentar sindicaciones y
actualizaciones sin borrar el historial ni mezclar fuentes.
