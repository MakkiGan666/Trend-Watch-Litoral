# Interfaz del buscador público

Etapa implementada el 2026-10-23 en `feat/buscador-noticias`, sobre el backend
`22f249e`. Para probar desde un checkout limpio, ver la
[guía para compañeros](buscador-noticias-probar.md).
No cambia el servicio, el contrato de la API ni la migración 0011. No hay índices,
dependencias, ingesta ni cambios de clasificación.

## Recorrido y presentación

`GET /buscar/` reutiliza directamente `buscar()`; no llama a la propia API.
Sin consulta o sólo espacios permitidos muestra el formulario sin consultar noticias.
Con consulta válida muestra total exacto, orden del servicio, 20 resultados y enlaces
anterior/siguiente conservando la consulta normalizada. No genera un enlace por página.
Consulta/página inválida devuelve 400, conserva el texto y muestra el error del servicio.
Cero resultados devuelve 200. Sólo GET; no se capturan errores internos como listas vacías.
Se ven fuente, fecha efectiva (etiqueta «Capturada» cuando corresponde), detalle interno
por `reverse`, imagen opcional y extracto contextual. No hay acciones administrativas.

La lupa está en `base.html` e `inicio.html` (esta última no hereda la base).
Categorías sólo sobrescribe `categories_nav` y recibe el mismo fragmento. Se inspeccionaron
Login y Litoral: sus rutas redirigen a Inicio/modal y Categorías respectivamente; no se
modificaron esas plantillas inactivas. La lupa está disponible con y sin sesión.

Sin JS queda un enlace accesible a `/buscar/`. Con JS aparece un botón con nombre,
`aria-controls` y `aria-expanded`: abre una fila, enfoca el campo, conserva su valor
al plegar y devuelve foco al cerrar o Escape. Abrir búsqueda cierra el menú móvil;
abrir menú/cuenta cierra búsqueda. Formularios GET con etiquetas funcionan mediante
botón o Enter nativo; no se agregan fetch, autocompletado ni cargas artificiales.
CSS reutiliza tokens, superficies y foco existentes, con movimiento reducido.
A 320 px la cuenta ocupa una segunda fila; la barra utiliza todo el ancho disponible.

## Seguridad y Unicode

`presentacion_busqueda.py` usa `plegar` V1 del backend y mapea cada carácter de `lower()`
a su posición NFC de origen. Cubre expansión de `İ`, tildes, diéresis, ñ/n y solapamientos.
Une intervalos y entrega segmentos de texto: sólo la plantilla emite `<mark>` estático.
Todos los segmentos, consulta, fuente y atributos se autoescapan. No usa `safe`,
`mark_safe` ni `innerHTML`. Los originales almacenados se conservan.

Las imágenes admiten http/https sin credenciales o rutas desde la raíz local. Rechaza
protocolos activos, URLs relativas a protocolo, barras inversas y controles, también
codificados. Una imagen fallida se oculta sin ocultar título/enlace; sin JS es decorativa
(`alt=""`) y el texto sigue disponible. No se usa contenido completo en resultados.

## Archivos

- Vista y ruta: `app/core/views_buscador.py`, `app/core/urls.py`.
- Presentación y pruebas: `app/core/presentacion_busqueda.py`, `app/core/test_busqueda_html.py`.
- Página: `app/core/templates/core/buscar.html`; cinco fragmentos `_search_*.html`.
- Integración: `app/core/templates/base.html`, `app/core/templates/inicio.html`.
- Recursos: `app/static/css/news-search.css`, `app/static/js/news-search.js`.
- Herramientas: `tools/buscador/validar_generadas.{py,sh}` (selección de pruebas),
  `previsualizar_busqueda.{py,sh}`, `revisar_frontend.{py,mjs}`.
- Este documento, enlaces desde documentos existentes, resultados compactos y capturas.

## Verificación reproducible

Desde el worktree, sin usar Compose ni la base habitual:

```bash
TW_BUSCADOR_FRONTEND=1 bash tools/buscador/validar_generadas.sh sqlite
TW_BUSCADOR_FRONTEND=1 bash tools/buscador/validar_generadas.sh postgresql
```

Usan contenedores/tmpfs propios y migraciones desde cero. Etiquetas exactas:
`core.test_busqueda_html core.test_buscador core.test_texto_busqueda core.test_fechas
core.test_perfil core.test_navegacion_admin core.test_integracion_pr24 core.test_categorias_compat`.

| Motor | Resultado | Tiempo de pruebas | Check Django |
|---|---|---:|---|
| SQLite | 89 ejecutadas, OK, 2 omitidas por motor | 33.166 s | 0 incidencias |
| PostgreSQL/PostGIS | 89 ejecutadas, OK, 1 omitida por motor | 45.714 s | 0 incidencias |

Las 11 pruebas nuevas cubren presentación/escape, Unicode y solapamientos, protocolos,
acceso anónimo, inicial sin consulta de noticias, contenido sin clasificar, 2 SELECT
sin escrituras/HTTP externo, errores, paginación, fechas, métodos y propagación de errores.
El control de migraciones confirma cero pendientes. `makemigrations --check` sigue
saliendo 1 por las cuatro diferencias previas de id (`publicaciontema`, `tematrend`,
`userauditoria`, `votopublicacion`); no hay diferencias nuevas. Evidencia compacta:
[buscador-noticias-frontend-resultados.json](buscador-noticias-frontend-resultados.json).
No se repitieron mediciones ni la suite completa.

Se publican dos capturas representativas; las otras tres se conservan localmente.
Los JSON registran los cinco nombres históricos, aunque no todos los PNG se publican.

Firefox 145.0.1 mediante BiDi y Node 20, sin paquetes adicionales: 17 comprobaciones
con JS y 3 sin JS, todas conformes. Capturas revisadas: escritorio 1440×1000,
resultados/Inicio móvil 390×844 y cuenta autenticada 320×800. Se bloqueó el tráfico
externo (incluidas fuentes web); las capturas usan la tipografía alternativa local.

- [Escritorio](capturas/buscador/resultados-escritorio.png)
- [Cuenta a 320 px](capturas/buscador/cuenta-movil-320.png)
- [Comprobaciones JS](capturas/buscador/revision.json) y [sin JS](capturas/buscador/revision-sin-js.json).

La automatización comprueba apertura/cierre, Escape/foco, conservación, menú/cuenta,
no desbordes, estados y miniaturas fallidas. La activación/envío se hace con `click()`
del control: BiDi entregó eventos Enter/Espacio sin su acción nativa en este entorno.
**Pendiente manual:** Enter/Espacio nativos, recorrido Tab/lector de pantalla, dispositivo
real y fuentes web. No se declaran esas comprobaciones realizadas. Se observó además
que el modal previo intenta enfocar antes de añadir `is-open` en un animation frame
(`trendwatch.js` y CSS intactos en HEAD); su foco inicial puede quedar en body. No se
refactorizó autenticación. Su apertura/cierre y Escape con un campo enfocado funcionan.

## Previsualización aislada

La [guía de prueba](buscador-noticias-probar.md) incluye clonación, construcción de
la imagen necesaria, arranque, uso y cierre. No requiere una imagen privada ni archivos
locales de quien desarrolló esta rama. La revisión de navegador es opcional y necesita
Firefox con BiDi y Node 20, además de Python 3.

El launcher monta código de sólo lectura y SQLite/secret aleatorio en tmpfs, aplica
migraciones y crea 43 noticias sintéticas sin IA/categoría/departamento. Usa una red
propia sin NAT y bloquea conexiones salientes en Python. Cotizaciones e imágenes
son locales. No carga dotenv ni credenciales reales. Las rutas `/preview/*` sólo
existen en ese servidor; no se añaden a la aplicación. El cierre verifica etiquetas
del contenedor y red antes de borrarlos. El navegador también bloquea destinos externos;
el helper crea perfiles temporales y cierra sólo sus propios procesos.

Cada compañero genera su propio puerto y manifiesto temporal; no reutilizar URL ni
manifiesto de otro equipo. Para desplegar sigue siendo obligatorio aplicar 0011 antes
de servir este código. El respaldo y el arranque PostgreSQL se detallan en la guía.

## Bitácora

Se inspeccionó navegación propia y heredada, conservando la lógica del backend.
Se añadieron página SSR, fragmentos, estilos, mejora progresiva y pruebas. Se corrigieron
dos expectativas iniciales de pruebas (alertas del modal existente y rutas que redirigen).
Se verificaron SQLite y PostgreSQL secuencialmente, luego revisión visual con datos
sintéticos y JS deshabilitado; las imágenes lazy se forzaron a cargar sólo desde el
controlador para comprobar su fallo. No se tocaron datos reales ni recursos ajenos.
Sin commit, push ni merge; los artefactos históricos ajenos a esta etapa se preservaron.

Preparación para publicación: instrucciones de checkout limpio y respaldo añadidas;
se seleccionaron dos capturas, sin modificar código ejecutable ni repetir las suites.
Los resultados anteriores se reutilizan porque el código probado es idéntico.
