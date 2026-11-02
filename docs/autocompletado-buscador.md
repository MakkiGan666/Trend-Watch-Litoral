# Autocompletado del buscador público

Integración selectiva de `feat/autocompletado-buscador` sobre
`codex/integracion-pr34`, después de las correcciones de PR #36. No requiere
migraciones nuevas ni cambia permisos, filtros o clasificación.

## Comportamiento

Los formularios compartidos de la barra y `/buscar/` ofrecen hasta cinco términos
extraídos de títulos y cuatro noticias relacionadas. El endpoint público de
lectura es `GET /api/publicaciones/sugerencias/?q=...` y devuelve `consulta`,
`terminos` (`texto`, `consulta`) y `noticias` (`titulo`, `url` local de detalle).

Comparte la validación y el alcance de la búsqueda actual: entre 2 y 150
caracteres NFC, hasta diez palabras; ignora mayúsculas y tildes vocálicas, y
conserva la distinción entre `n` y `ñ`. Completa la última palabra manteniendo el
contexto anterior. Prioriza frecuencia para términos y coincidencias en título
para noticias; usa fechas y claves como desempates. Las noticias sin clasificación
territorial o IA también pueden encontrarse, igual que en la búsqueda existente.

Se ejecutan dos consultas de lectura con parámetros y límites en SQL; no se carga
el corpus en Python ni se llama a servicios externos. PostgreSQL tokeniza con sus
funciones nativas; SQLite tiene un adaptador por conexión. Las respuestas llevan
`Cache-Control: no-store`; entradas inválidas reciben 400 y otros métodos 405.

## Interacción y accesibilidad

- Espera de 300 ms al escribir; cancela solicitudes anteriores y descarta sus
  respuestas tardías. Tiempo máximo de solicitud: cinco segundos.
- Combobox con listbox, grupos, estado anunciado y opción activa identificada.
  El foco permanece en el campo; flechas recorren opciones y Enter selecciona.
- Enter sin opción seleccionada conserva el envío GET normal. Escape cierra las
  sugerencias; en la barra, un segundo Escape cierra el buscador y restaura el foco.
- El toque selecciona al soltar; arrastrar o cancelar un gesto no selecciona.
- Las etiquetas y los destinos deben ser cadenas no vacías tras quitar espacios.
  Las entradas ausentes o de tipo incorrecto se omiten sin crear opciones o grupos
  vacíos. Los textos se insertan con `textContent`, nunca como HTML. Solo se aceptan
  enlaces de noticias del mismo origen con la ruta de detalle esperada; una URL
  malformada se omite sin descartar las otras entradas válidas.
- Cada formulario mantiene su estado independiente. La composición IME no genera
  consultas incompletas.
- Ante errores o resultados vacíos se cierra el panel y permanece el formulario.
  Sin JavaScript siguen disponibles el enlace de búsqueda, el GET y la paginación.
- El panel participa del flujo de la página y tiene altura limitada para móvil.

## Validación

```sh
python manage.py test core.test_sugerencias
python manage.py test core
python manage.py makemigrations --check --dry-run
```

Pruebas del controlador con jsdom instalado solo como herramienta de desarrollo:

```sh
NODE_PATH=/ruta/a/node_modules node tools/buscador/test_autocompletado.cjs
```

Las pruebas cubren normalización española, contexto, límites, ranking, caracteres
literales, cambios y borrado de noticias, consultas de solo lectura, alcance público,
seguridad del texto, cancelación, teclado y gestos táctiles. La validación de navegador
se realiza en una base PostgreSQL aislada con noticias sintéticas; no requiere copiar
cuentas o publicaciones reales. Las evidencias de esta preparación permanecen fuera
del repositorio.

La salida está acotada, pero la tokenización consulta títulos del conjunto elegible;
para un archivo grande conviene medir latencia y carga antes de ampliar el despliegue.


## Alcance operativo y crecimiento

La auditoría focalizada de PR #37 midió el servicio real en PostgreSQL 17 con
publicaciones sintéticas y caché caliente. Medianas de tres muestras para `mi`:

| Publicaciones | Mediana del servicio |
| ---: | ---: |
| 140 | 11 ms |
| 1.000 | 33 ms |
| 10.000 | 187 ms |
| 50.000 | 1.073 ms |

Con 50.000 publicaciones, cuatro llamadas concurrentes tardaron entre 2,63 y
3,06 segundos. Un prefijo sin coincidencias también superó un segundo. Son tiempos
locales del servicio, sin HTTP, no percentiles ni garantías de producción.

**Alcance recomendado de esta entrega: el corpus actual de 140 publicaciones y
revisión local/controlada.** No se certifica capacidad para exposición pública con
tráfico no acotado ni para crecimiento a decenas de miles de noticias. Este alcance
es una restricción operativa documentada: el código no aplica un tope de registros
ni una cuota de solicitudes. Antes de ampliar el corpus o el tráfico hay que medir
latencia y carga concurrente representativas y acordar el presupuesto de respuesta.
Las cifras con 1.000 noticias son orientativas, no una ampliación ya validada del
alcance real.

`LIMIT 5` limita la salida, pero la consulta de términos tokeniza todos los títulos
elegibles antes de agrupar. El debounce y AbortController del navegador no garantizan
cancelación del SQL. No hay una mitigación nueva de esta carga en esta corrección.

Se evaluó un prefiltro de subcadena en `titulo_busqueda` antes de tokenizar. No se
incorporó: plegar el título entero y plegar cada palabra no son intercambiables en
todos los casos Unicode. Por ejemplo, la normalización V1 de SQLite transforma
`ΟΣ'Α` en `οσ'α`, pero la palabra `ΟΣ` se pliega como `ος`: el prefijo `ος` puede
coincidir por palabra aunque falte en el título plegado. Un prefiltro genérico
cambiaría resultados; una variante solo para determinadas configuraciones de
PostgreSQL exigiría una justificación específica de colación. Además, no mejoraría
el peor caso de un prefijo frecuente presente en todos los títulos. No se alteró el
SQL ni su semántica, frecuencia, ranking o frescura.

Para crecer, evaluar una proyección de términos o reutilización de resultados con
invalidación correcta y protección de carga, con autorización y pruebas aparte.
No anteponer un límite arbitrario al corpus ni usar un caché obsoleto como sustituto:
eso cambiaría el contrato. Esta entrega no agrega tablas, índices o migraciones.
