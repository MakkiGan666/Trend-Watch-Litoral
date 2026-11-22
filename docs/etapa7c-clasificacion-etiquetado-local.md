# Etapa 7C Clasificación temática y etiquetado local

El comando `enriquecer_publicaciones_local` completa asociaciones temáticas y etiquetas faltantes de artículos con cuerpo. La simulación es el modo predeterminado. El comando se ejecuta bajo demanda, con reglas léxicas locales y con la extracción de etiquetas que ya usan las altas y ediciones.

## Diagnóstico de las reglas

La regla v2 del borrador ponderaba el título y el cuerpo usando prefijos. En el respaldo operativo produjo 97 propuestas sobre 2.374 artículos sin categoría. La revisión de 24 propuestas encontró cinco asignaciones incorrectas o secundarias. La repetición de vocabulario elemental y la coincidencia con instituciones como Casino Club podían desplazar el foco de la nota.

La versión v3 usa palabras completas agrupadas por familias léxicas. Las flexiones de una misma familia cuentan una vez por campo. El titular tiene más peso que la entrada, y el aporte del resto del cuerpo es limitado. Las expresiones temáticas reconocidas en el titular y las primeras 115 palabras sirven de ancla. Términos transversales como «estudiantes», «familia» o «aplicaciones» aportan menos evidencia. La categoría ganadora necesita un mínimo de puntaje, una ventaja frente a la segunda y corroboración temática. Ante un titular genérico, sólo confirma si la entrada aporta varias familias específicas y un ancla o corroboración posterior.

| Caso controlado | Resultado esperado |
| --- | --- |
| Casino Club publica una cartelera de espectáculos | Cultura |
| Desfile de la Estudiantina | Festividades |
| Muerte por descarga eléctrica en una escuela | Policiales |
| Fiesta de las Colectividades con un título centrado en la lluvia | Festividades si la entrada identifica el evento |
| Encuentro de clubes de lectura | Cultura |
| Medicina y educación con evidencia comparable | Abstención |
| «Saludó» sin vocabulario sanitario que corrobore | Abstención |

La extracción de etiquetas v2 limita la contribución de las repeticiones y prioriza términos del titular corroborados por el cuerpo. Excluye conectores y palabras de baja información. Conserva expresiones contiguas y nexos admitidos como «de» y «del». Las secuencias de nombres respetan la puntuación y los límites del texto. Si el título es genérico, el respaldo usa la entrada y genera hasta seis etiquetas. Se mantiene el límite general de 15 y el orden determinista.

## Ejecución y reanudación

Desde la raíz, con el entorno Django configurado para la base que se quiera consultar:

```bash
python app/manage.py enriquecer_publicaciones_local --limite 100
python app/manage.py enriquecer_publicaciones_local --aplicar --limite 100
python app/manage.py enriquecer_publicaciones_local --aplicar --limite 100 --despues-de-id 500
```

El comando devuelve un objeto JSON con `dry_run`, `cursor`, `hay_mas` y un resultado por artículo. Durante la simulación, los nombres de categorías y los slugs propuestos permiten revisar el lote antes de decidir si aplicarlo. `--dry-run` también puede indicarse explícitamente. El límite admite de 1 a 1000 candidatos por llamada y el cursor apunta al último ID terminado. Para aplicar lo simulado, se usa el mismo cursor inicial de la simulación.

Se recorren por ID los artículos completos a los que les falta categoría, etiquetas o ambas. `hay_mas` indica que la consulta vio otro candidato tras el límite. Si falla una escritura, las dos operaciones del artículo se revierten, el comando termina con error e informa el cursor previo. Las publicaciones anteriores quedan confirmadas. Si se pierde la salida, repetir desde el último cursor conocido conserva los resultados que ya existen. Los artículos con abstención avanzan el cursor del recorrido. Un barrido posterior desde cero vuelve a evaluar los faltantes.

## Criterios de aceptación

- La simulación sólo consulta la base. La aplicación bloquea la publicación y vuelve a comprobar el cuerpo y los vínculos antes de escribir.
- Un vínculo temático existente, incluido uno manual o histórico, conserva su identidad y procedencia. Un conjunto de etiquetas existente conserva sus vínculos, orden y fechas. Los artículos con ambos resultados salen de los lotes siguientes.
- Cada vínculo nuevo registra fecha, método y evidencia `cuerpo_completo`. Las categorías usan `clasificacion-reglas-v3` y las etiquetas `extraccion-etiquetas-v2`. Sus reglas no generan un valor numérico de confianza.
- Las fichas RSS y los registros sin cuerpo utilizable quedan fuera. El comando procesa categorías y etiquetas sin invocar análisis geográfico, sentimiento, proveedores externos o tareas RSS.
- La validación incluye PostgreSQL aislado para transacciones y concurrencia, SQLite en memoria para el flujo local y regresiones de clasificación, etiquetas, persistencia y dashboard.


## Auditoría comparativa de 7C.1

Se usó el mismo respaldo verificado, `trendwatch-pre-pr74-0036-20261122T002953Z.dump`. La restauración nueva coincidió con las huellas previas de publicaciones, asociaciones y sentimientos de la línea base `6300948`. Los 3.219 artículos completos del corpus proceden de El Territorio. Se ejecutaron dos simulaciones de solo lectura por versión en lotes de 500. En cada versión ambos resultados fueron idénticos.

| Métrica | Línea base 7C | Refinamiento 7C.1 |
| --- | ---: | ---: |
| Artículos con tema previo que se conserva | 845 | 845 |
| Artículos que admiten clasificación | 2.374 | 2.374 |
| Propuestas y cobertura | 97 (4,1 %) | 484 (20,4 %) |
| Abstenciones | 2.277 | 1.890 |
| Vínculos de etiquetas propuestos | 28.541 | 14.148 |
| Slugs distintos | 9.292 | 6.533 |
| Etiquetas por artículo, media | 8,87 | 4,40 |
| Artículos con alguna etiqueta | 3.219 | 3.219 |
| Tiempo de simulación | 67,71–75,52 s | 19,22–19,71 s |
| Tiempo de aplicación en la copia | 90,37 s | 54,08 s |
| Sentencias instrumentadas en la aplicación | 66.857 | 47.283 |
| Tiempo de la repetición idempotente | 44,22 s | 11,81 s |

La aplicación en la copia reprodujo la simulación y las asociaciones nuevas registraron la versión correspondiente, el método, la fecha y la evidencia de cuerpo completo. Los 845 vínculos temáticos previos conservaron exactamente sus filas y las 155 fichas RSS quedaron fuera. La copia original no contenía etiquetas previas. La repetición conservó todas las filas tras la primera aplicación, y el flujo de integración cubre etiquetas preexistentes con datos de prueba.

### Distribución temática

| Categoría | 7C | 7C.1 |
| --- | ---: | ---: |
| Cultura | 7 | 91 |
| Economía | 17 | 84 |
| Festividades | 18 | 65 |
| Política | 6 | 60 |
| Policiales | 8 | 52 |
| Educación | 16 | 36 |
| Deportes | 3 | 34 |
| Turismo | 10 | 28 |
| Salud | 3 | 22 |
| Sociedad | 3 | 5 |
| Tecnología | 3 | 4 |
| Ambiente | 3 | 3 |


### Revisión editorial pareada

Se volvieron a revisar los mismos 42 artículos. De las cinco propuestas incorrectas o secundarias en la línea base, cuatro cambiaron a una categoría más adecuada y una a abstención.

| ID | Línea base | 7C.1 | Foco |
| ---: | --- | --- | --- |
| 3954 | Deportes | Cultura | Cartelera de espectáculos de Casino Club |
| 5057 | Educación | Festividades | Desfile de la Estudiantina |
| 4584 | Educación | Policiales | Muerte por descarga eléctrica |
| 5880 | Sociedad | Abstención | Fiesta de las Colectividades con lluvia destacada en el titular |
| 4882 | Sociedad | Cultura | Encuentro de clubes de lectura |

Las 15 propuestas plausibles de la muestra original conservaron su categoría. Dos de las cuatro propuestas mixtas pasaron a abstención. Seis de las doce abstenciones originales ahora tienen propuesta. Cinco tienen un foco reconocible y una combina turismo y festividades. En una segunda revisión estratificada de 24 propuestas de 7C.1, dos por categoría, quedaron 20 plausibles, tres mixtas y una discutible. El artículo 5749 recibió Sociedad pese a centrarse en un incendio y la respuesta de bomberos. La evaluación usa título y extractos. La muestra pareada incluye casos que guiaron el refinamiento, y la segunda muestra comparte algunos artículos. Las proporciones describen las muestras y el corpus de un solo medio limita su generalización.

En la muestra fija los vínculos propuestos pasaron de 384 a 190. El conjunto de doce palabras genéricas auditadas pasó de 15 apariciones en 10 artículos a cero. En el corpus, `porque` (101), `parte` (85) y `hace` (56) pasaron a cero. Desaparecieron `adorni-fin`, `tecnologicas-trump` y el fragmento `club-posadas`. Persisten palabras generales como `vida` y `mundo` en el ranking. Su relevancia depende del artículo.

### Treinta etiquetas más frecuentes por versión

| Puesto | 7C | Frecuencia | 7C.1 | Frecuencia |
| ---: | --- | ---: | --- | ---: |
| 1 | `posadas` | 246 | `posadas` | 86 |
| 2 | `nacional` | 190 | `santo-tome` | 78 |
| 3 | `gobierno` | 144 | `fiesta` | 65 |
| 4 | `argentina` | 135 | `buenos-aires` | 56 |
| 5 | `milei` | 103 | `brasil` | 45 |
| 6 | `porque` | 101 | `inmigrante` | 45 |
| 7 | `pais` | 90 | `obera` | 45 |
| 8 | `parte` | 85 | `estudiantina` | 43 |
| 9 | `santo-tome` | 78 | `uruguay` | 42 |
| 10 | `brasil` | 76 | `casino-club-posadas` | 41 |
| 11 | `historia` | 73 | `milei` | 41 |
| 12 | `trabajo` | 73 | `argentina` | 39 |
| 13 | `musica` | 72 | `iguazu` | 39 |
| 14 | `personas` | 72 | `millones` | 36 |
| 15 | `semana` | 69 | `vida` | 32 |
| 16 | `vida` | 69 | `gobierno` | 31 |
| 17 | `estudiantes` | 67 | `jardin-america` | 31 |
| 18 | `fiesta` | 67 | `casino-club` | 30 |
| 19 | `obera` | 67 | `mundial` | 30 |
| 20 | `millones` | 66 | `pais` | 30 |
| 21 | `familias` | 63 | `historia` | 28 |
| 22 | `iguazu` | 62 | `mundo` | 28 |
| 23 | `encuentro` | 59 | `eldorado` | 27 |
| 24 | `espacio` | 59 | `noche` | 27 |
| 25 | `familia` | 57 | `guarani` | 26 |
| 26 | `actividad` | 56 | `musica` | 26 |
| 27 | `casa` | 56 | `edicion` | 25 |
| 28 | `ciudad` | 56 | `hombre` | 25 |
| 29 | `hace` | 56 | `passalacqua` | 25 |
| 30 | `noche` | 56 | `semana` | 25 |
