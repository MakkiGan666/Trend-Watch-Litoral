# Categorías, portada regional y lecturas

## Navegación

- `/categorias/` presenta las 12 categorías del proyecto. Cada tarjeta abre
  `/categorias/<slug>/`, un listado paginado de las publicaciones que tienen
  esa categoría **asociada en la base**. Una noticia sin categoría confirmada
  no se atribuye por su sección RSS.
- El bloque «Municipios» conserva los 17 accesos por **departamento** y el mapa
  existente. La leyenda indica que cada departamento agrupa municipios.
- El panel de análisis vacío se retiró.

## Inicio y tendencias

- Inicio muestra hasta 15 noticias regionales **por cada categoría confirmada**,
  en carruseles independientes. La señal provincial es un departamento detectado
  o una referencia explícita a Misiones en el título. Entre las 300 regionales
  más recientes de cada categoría se ponderan actualidad y lecturas.
  Las categorías sin noticias provinciales confirmadas muestran un mensaje vacío;
  no se rellenan con noticias nacionales ni con clasificaciones supuestas.
  Este criterio es una heurística; no equivale a una verificación editorial.
- `ClicPublicacion` registra un lector por noticia y actualiza su última visita
  como máximo una vez al día. Anónimos y superusuarios no alteran el ranking.
  Las recargas no generan clics extra.
- Las tendencias usan clics de los últimos siete días. Al registrar el primer
  clic de una noticia categorizada, se relaciona su `Tema` con `Trend` mediante
  `TemaTrend`. Cuando todavía no hay clics, se muestra una selección regional
  reciente rotulada como tal. No se usa IA para ordenar estas señales.
- «Mis guardados» recomienda hasta tres noticias de categorías o departamentos
  relacionados con lo guardado o valorado positivamente; excluye lo ya guardado,
  lo ya valorado positivamente y lo valorado negativamente.

## Comentarios

- El formulario rechaza expresiones ofensivas conocidas, aun con tildes o
  sustituciones simples. Los comentarios nuevos y editados quedan pendientes
  de aprobación. Solo el autor puede ver, editar o quitar los suyos pendientes.
- Los administradores aprueban o rechazan desde Django Admin → Comentarios.
  La migración `0015` devuelve a revisión los comentarios previos que
  coincidan con el filtro. Está separada de `0014` para que también se aplique
  en bases donde `0014` ya se ejecutó.
- Ningún filtro automático comprende todas las variantes del lenguaje ni el
  contexto. La aprobación humana sigue siendo necesaria.

## Ingesta automática

- El servicio Docker `ingesta` ejecuta `ingestar_recientes`: consulta los RSS
  configurados cada 300 segundos, sin IA por defecto, y deduplica por URL/hash.
  Corre separado del servidor web y reintenta en el ciclo siguiente si falla
  un feed. El registro queda en la base local, no en Git.
- Para revisar una sola vez, después de aplicar migraciones:

  `docker compose exec web python manage.py ingestar_recientes --una-vez`

- Si el servicio permanece detenido más tiempo que el histórico visible en los
  RSS, puede faltar cobertura. En ese caso se utiliza la ingesta histórica del
  período afectado, que también omite noticias existentes.

## Puesta en marcha local

Desde la raíz del proyecto, con la base local respaldada y los contenedores
`db` y `web` encendidos:

1. `docker compose exec web python manage.py migrate`
2. `docker compose exec web python manage.py check`
3. `docker compose exec web python manage.py test core.test_portada_regional core.test_comentarios core.test_sentimiento_comentarios core.test_clasificacion core.test_indicadores_inicio --noinput`
4. `docker compose up -d ingesta`

La migración `0013` depende de la migración de unión `0012_merge_20261027_0946`
que reúne las dos ramas `0011` presentes en el árbol de trabajo actual. Ambas
deben viajar juntas cuando se prepare el PR.
