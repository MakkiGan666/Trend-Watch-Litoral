# Fase 2.3 — Territorio, IA, identidad y límites

Base: dced765a0d1453a34784c12056a49ee9cf239338, rama
fix/stabilizacion-pr23-fase1-1. Inicio limpio. Las decisiones funcionales de PR #23
y PR #24 prevalecen sobre CAT-01: se conservan las doce categorías y el diseño
existente. No se modifican catálogo, modelos, migraciones ni datos almacenados.

No se encontró un documento versionado con los rótulos H5/H8/H9/H10/H11 en docs/
o tools/. El contraste se hizo contra los problemas indicados por el usuario,
el código actual, sus regresiones y las notas de fases anteriores. No se presenta
como nueva una reparación ya realizada. La base de 156 pruebas PostgreSQL/PostGIS
aprobadas es la validación informada del checkpoint anterior, no de este cambio.

## H5: reproducciones y corrección territorial

Antes de editar se reprodujeron con el clasificador real, sin Django ni red:

| Entrada | Resultado anterior | Resultado corregido |
| --- | --- | --- |
| El acto será el 25 de Mayo | 25mayo | vacío |
| Festejos en San Pedro, Buenos Aires | sanpedro | vacío |
| Obras en el municipio de Guaraní | vacío | obera |
| Obras en el departamento Guaraní | vacío | guarani |
| La capital provincial de Corrientes | capital | vacío |

Las fechas/efemérides 9 de Julio, 25 de Mayo y Dos de Mayo requieren ahora una
referencia explícita a localidad/municipio/ciudad. Capital sola o capital provincial
no son evidencia de Capital de Misiones; capital misionera y departamento Capital
sí lo son. Se distingue Guaraní municipio de Guaraní departamento. Se amplía la
lista de homónimos y se descartan menciones con jurisdicciones externas explícitas
adyacentes. Se mantiene la regla de empate: ningún departamento si no hay ganador.

Son reglas conservadoras, no un geocodificador. No detectan todos los homónimos ni
todas las formas de referenciar otra provincia. Pueden omitir una localidad real
sin evidencia suficiente. El mapa exacto `departamento_de_ubicacion` conserva su
contrato: nombres como Puerto Rico sin contexto siguen siendo interpretables como
localidades misioneras. No se reescriben Locacion ni departamentos históricos.
Las ubicaciones propuestas por Gemini siguen sujetas al validador existente.

## H8/H9: IA incompleta, confianza y persistencia

La regla de confianza decía exigir evidencia en título, pero tres repeticiones en
el cuerpo daban Salud/segura=True con título Información general. Ahora además del
puntaje/margen existente exige evidencia en título. La propuesta no se elimina:
queda no confirmada, puede ir a IA o persistirse sin asociación según Fase 2.2.
Las secciones específicas y los títulos claros conservan su clasificación.

Las respuestas de clasificación parciales y [] ya eran admisibles: sólo confirman
los índices efectivamente validados; los demás siguen inciertos. Se conserva esa
política y se añade un aviso con la cantidad resuelta, sin registrar contenido.
Índices ajenos/repetidos, claves duplicadas, categorías desconocidas y estructuras
inválidas siguen invalidando esa respuesta antes de escribir. No se mezcla el
protocolo temático con polaridad/confianza/localidades.

El validador de sentimiento ya exigía todos los campos y aceptaba localidades=[];
la conversión de confianza local de porcentaje a [0,1] y la transacción/idempotencia
estaban corregidas. No se cambiaron esas fórmulas ni contratos. Se agregan pruebas
para respuestas incompletas, lista vacía válida, fallo después de la primera
ubicación, rollback completo y reintento explícito sin duplicación. Se amplía el
arnés con sus regresiones existentes de integridad/concurrencia/confianza local.

Ambos validadores de respuesta IA rechazan textos de más de 256 Ki caracteres
antes de json.loads. Este límite protege parseo/persistencia; no limita los bytes
que la SDK ya haya recibido ni el tiempo de una llamada real a Gemini.

## H10: equivalencia conservadora sin rehash

Se podía persistir dos veces una URL por diferencias de mayúsculas en esquema/host
o presencia explícita de :443, aunque el transporte alcanzara el mismo destino.
La nueva clave de comparación sólo normaliza esos componentes de URLs HTTPS
admitidas. Se conserva literalmente:

- Ruta y mayúsculas de ruta, escapes y barras finales.
- Parámetros, valores, orden, repeticiones y parámetros de seguimiento.
- Diferencia entre www y dominio raíz; no se equipara HTTP a HTTPS.
- Presencia de query vacía. Los fragmentos siguen rechazados por la política previa.

No cambia generar_hash, el enlace almacenado ni los hashes históricos. RSS e
histórico detectan equivalentes del lote y de publicaciones previas. La búsqueda
de legado filtra por sufijo ruta/query y después compara la clave completa en
Python, para no confundir rutas/query aunque un LIKE del backend sea menos estricto.
No fusiona publicaciones históricas que ya eran duplicadas; las cuenta sin repetir
el contador y conserva sus relaciones.

Límites: la consulta adicional por sufijo puede escanear la tabla, porque no existe
índice canónico. No se hace búsqueda de equivalencia histórica para URL sin ruta.
La unicidad concurrente continúa protegida por hash exacto; dos procesos simultáneos
con aliases diferentes todavía pueden crear dos hashes distintos. Resolverlo con
una identidad canónica única requiere coordinar esquema y migración de identidades,
fuera de esta fase. El alta manual/admin conserva su identidad URL/título existente;
no se cambia unilateralmente ese contrato. No hay afirmación de canonicalización
completa ni de equivalencia entre redirecciones de destinos distintos.

## H11: parámetros y descarga proporcionada

- Gemini rechaza batch_size no entero positivo, incluyendo bool, antes de consultar
  pendientes o invocar al cliente. Las rutas públicas siguen usando sus valores fijos.
- El scraper alternativo deja de aceptar True como límite 1. RSS/histórico oficiales
  ya rechazaban límites negativos, cero, booleanos y tipos inválidos.
- El histórico valida pausa finita no negativa antes de crear auditoría/descargar;
  pausa=0 conserva su uso legítimo en pruebas y ejecuciones deliberadas sin espera.
- Descarga valida timeout finito positivo; no admite None como espera ilimitada.
- Se conserva el tope de 8 MiB y las seis respuestas máximas en redirecciones. Se lee
  el cuerpo mediante read1 en bloques de hasta 64 KiB, acumulando el límite de tamaño.
  Un reloj monotónico comparte el presupuesto configurado entre saltos/lecturas,
  reduce el timeout del socket al tiempo restante y evita renovarlo por cada bloque.
- Se retiene la referencia al socket antes de getresponse: HTTPConnection puede
  liberarla cuando Connection: close, aunque HTTPResponse aún conserve su descriptor.
  Una prueba ejercita ese caso con el parser HTTP real y un socket/archivo simulados.

No se introdujeron reintentos automáticos de HTTP, Gemini ni escrituras. Cada GET
mantiene una tentativa y sus redirecciones acotadas. Un fallo se informa por las
rutas existentes; reintentar ingesta o IA es una nueva operación explícita, protegida
por las comprobaciones de idempotencia ya existentes. No se duerme ni reintenta
un error de persistencia dentro de la transacción.

Límites de tiempo pendientes: getaddrinfo del sistema no se puede interrumpir con
este timeout. La lectura de cabeceras del parser HTTP estándar y los handshakes
conservan los timeouts de socket, sin una garantía estricta de duración total frente
a goteo de cabeceras. El presupuesto se comprueba al recuperar control. No se afirma
un deadline completo de transporte. La SDK Gemini conserva su política de tiempo;
no se configuraron retries nuevos ni se hicieron llamadas reales para verificarla.
Tampoco se limita en esta fase la cantidad total de sitemaps/candidatos del período.

## Pruebas y alcance

Ejecuciones locales:

- Fase 2.3: **21/21**, también con -O. Código real con modelos/SDK/sockets/reloj
  simulados; sin base, red ni dependencias nuevas.
- Regresiones anteriores: arnés **32/32**, ingesta **26/26**, categorías **16/16**,
  fechas **9/9**; frontend **9 escenarios**.
- Compilación estática de Python nuevo/modificado y git diff --check correctos.

Una primera prueba de socketpair local fue bloqueada por el sandbox al enviar;
no hubo elevación ni acceso externo. La versión final usa un archivo en memoria y
socket simulado, sin llamadas nativas de red. No se afirma integración real del
transporte TCP/TLS en esta tarea.

Se agregan **17 pruebas ORM** en core.test_fase2_3. El bloque nuevo también incluye
30 existentes: GeminiIntegridadTestCase (15), GeminiTransaccionesTestCase (1),
EscritoresLocalesIntegridadTestCase (8), GeminiResultadosTestCase (6).
Bloque Fase 2.3: **47**; acumulado esperado: **203** (156 + 47).
Son pruebas pendientes en PostgreSQL, no resultados ejecutados aquí.

Django no está disponible en el Python local. No se ejecutaron check, suite ORM,
Docker, servicios externos, scraping, Gemini, bases persistentes ni migraciones.
No hubo commits, staging, push o integración con PR #24. No se modificó otro worktree.

El arnés sólo amplía etiquetas; conserva sus controles de daemon local, red isolated,
contenedores propios, tmpfs, código read-only e identidad de PostgreSQL antes de
habilitar escrituras. Comando único para ejecución manual posterior autorizada,
con imágenes ya locales y sin sudo:

```sh
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 /usr/bin/python3 -B /home/sebas/Escritorio/trendwatch-pr23-estabilizacion/tools/fase1_1/run.py
```

Esperar check correcto y bloques 64, 54, 14, 24 y 47, sin skips inesperados. Las
156 aprobadas previas deben volver a validarse sobre el árbol actual. La selección
sigue sin equivaler a la suite completa del repositorio.


## Validación integral posterior completada

El usuario confirmó la ejecución satisfactoria en PostgreSQL/PostGIS descartable:

- Fases 1.1 a 2.2: **156/156 pruebas aprobadas**.
- Fase 2.3 y regresiones adicionales: **47/47 pruebas aprobadas**.
- Total: **203/203 pruebas aprobadas**.
- Django System Check: **sin incidencias**.

Esta confirmación posterior sustituye el estado pendiente de la sección anterior,
que se conserva como historial de preparación. Siguen vigentes los riesgos y
límites documentados: territorio heurístico, equivalencia URL conservadora sin
unicidad canónica concurrente, coste de búsqueda por sufijo y ausencia de un
deadline total estricto para DNS/cabeceras o para la SDK Gemini. La selección del
arnés no equivale a toda la suite del repositorio ni a una prueba de red real.

Durante la preparación de este checkpoint sólo se actualizó este README; no se
modificó código funcional ni se ejecutaron Docker, scraping, Gemini, HTTP externo,
servicios o migraciones. Se conserva la prioridad funcional de PR #23 y PR #24,
el catálogo de doce categorías y las asociaciones históricas.
