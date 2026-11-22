# Etapa 7C Clasificación temática y etiquetado local

El comando `enriquecer_publicaciones_local` completa asociaciones temáticas y etiquetas faltantes de artículos con cuerpo. La simulación es el modo predeterminado. El comando se ejecuta bajo demanda, con reglas léxicas locales y con la extracción de etiquetas que ya usan las altas y ediciones.

## Diagnóstico de las reglas

La regla temática previa da peso 3 al título y 1 al cuerpo por ocurrencia. Confirma si hay una raíz de la categoría ganadora en el título y su puntaje duplica al segundo, o si recibe una sección editorial conocida. El fallback «Sociedad» es una propuesta sin confirmación cuando falta evidencia.

| Caso controlado | Regla previa sin sección | Criterio del lote 7C |
| --- | --- | --- |
| «Hospital incorpora médicos» con pacientes en el cuerpo | Salud | Salud |
| «Docentes de la universidad» con clases y escuelas en el cuerpo | Educación | Educación |
| «Hospital» con un cuerpo sin términos de salud | Salud | Abstención |
| «Hospital» con la misma palabra repetida en el cuerpo | Salud | Abstención |
| «Saludó al público» con el verbo repetido | Salud por coincidencia de prefijo | Abstención |
| «Médicos y docentes» con pacientes y estudiantes | Propuesta sin confirmar | Abstención |
| Título genérico con términos de salud sólo en el cuerpo | Propuesta sin confirmar | Abstención |

En el lote 7C cada raíz cuenta una vez por campo. La categoría ganadora necesita evidencia en título y cuerpo, al menos dos raíces distintas entre ambos y un puntaje como mínimo doble del de la segunda. Se usa el catálogo existente y el texto de la publicación. El circuito no deduce una sección a partir de la fuente. La matriz es una prueba de comportamiento con ejemplos controlados. Las coincidencias léxicas todavía dependen de la cobertura de raíces, el contexto y el uso de prefijos.

La extracción de etiquetas usa el algoritmo existente, con hasta 15 etiquetas, orden determinista y slugs únicos. Las etiquetas son independientes de la decisión temática y pueden existir cuando la clasificación se abstiene.

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
- Cada vínculo nuevo registra fecha, método y evidencia `cuerpo_completo`. Las categorías usan `clasificacion-reglas-v2` y las etiquetas `extraccion-etiquetas-v1`. Sus reglas no generan un valor numérico de confianza.
- Las fichas RSS y los registros sin cuerpo utilizable quedan fuera. El comando procesa categorías y etiquetas sin invocar análisis geográfico, sentimiento, proveedores externos o tareas RSS.
- La validación incluye PostgreSQL aislado para transacciones y concurrencia, SQLite en memoria para el flujo local y regresiones de clasificación, etiquetas, persistencia y dashboard.
