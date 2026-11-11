# Etiquetas navegables de noticias

Cada publicación puede tener hasta 15 etiquetas ordenadas. En la lista de una categoría se muestran las primeras cinco; en el detalle se muestran todas. Cada etiqueta enlaza a `/etiquetas/<slug>/`, una lista paginada de publicaciones con esa misma etiqueta. Desde cualquiera de esas noticias se puede seguir otra etiqueta.

Las etiquetas se extraen de forma determinista del título y del contenido. No se llama a servicios de IA ni se calcula el resultado en cada visita. Este documento describe las asociaciones de origen `lexico`. Las etiquetas temáticas de IA (origen `ia`) comparten el catálogo, pero se generan y sincronizan aparte, y nunca se borran al recalcular las léxicas. Ver `seguimiento-ia-y-etiquetas-tematicas.md`. Al crear o editar título o contenido, las asociaciones se actualizan. Las noticias anteriores requieren el comando de carga.

Después de `python manage.py migrate`, ejecutar por lotes:

```text
python manage.py generar_etiquetas --limite=200
python manage.py generar_etiquetas --despues-de-id=<cursor impreso> --limite=200
```

Repetir con el cursor impreso hasta que el comando indique `Publicaciones procesadas: 0`. El comando recalcula el lote de forma segura, por lo que un lote puede repetirse si se interrumpe. Revisar una muestra de etiquetas antes de completar todo el archivo; el método léxico puede escoger expresiones poco útiles en algunas noticias.


## Sincronización y escrituras masivas

`Publicacion.save()` mantiene el texto y sus etiquetas en una transacción. Las señales comparan el texto persistido antes y después: cambiar sólo fuente, imagen, departamento o `procesado_ia`, o guardar el mismo texto, no ejecuta la extracción. Las cargas `raw` de fixtures no generan asociaciones; deben cargarlas explícitamente o ejecutar después el comando.

El servicio bloquea la publicación y relee su título y contenido desde la misma base de datos antes de extraer etiquetas. Una instancia antigua no vuelve a imponer asociaciones de un texto anterior. En PostgreSQL las sincronizaciones de la misma publicación se serializan. Los slugs compartidos se crean en orden estable; no se silencian errores de integridad ni se reintentan transacciones parcialmente fallidas. SQLite no ofrece bloqueo de fila: las pruebas SQLite no validan concurrencia PostgreSQL.

Si slugs y posiciones ya coinciden, no se borran ni insertan asociaciones. Si cambian, se reemplaza la secuencia atómicamente: una actualización diferencial de posiciones podría colisionar con `posicion_unica_por_publicacion` al intercambiar dos etiquetas. El catálogo de etiquetas compartidas no se elimina ni se renombran entradas existentes.

`QuerySet.update()`, `bulk_update()` y `bulk_create()` no emiten señales ni llaman a `save()`. No tienen sincronización automática. No se usan para cambiar texto en los flujos productivos de creación, edición o ingesta revisados; `medir_buscador` sí crea datos sintéticos con bulk. Una nueva escritura bulk de texto debe sincronizar explícitamente cada publicación afectada, dentro de la misma transacción y usando el mismo alias. Por ejemplo:

```python
from django.db import transaction
from core.models import Publicacion
from core.services.etiquetas import sincronizar_etiquetas

with transaction.atomic():
    publicacion = Publicacion.objects.select_for_update().get(pk=identificador)
    Publicacion.objects.filter(pk=publicacion.pk).update(titulo=titulo, contenido=contenido)
    sincronizar_etiquetas(publicacion)
```

Para varios registros, bloquearlos por PK ascendente antes de escribir. Para `bulk_create()`, sincronizar las instancias devueltas con PK dentro de la misma transacción; no usar `ignore_conflicts` como sustituto de esa identificación. Escrituras SQL externas y cargas raw tienen la misma limitación. Si ya se ejecutó un bulk sin sincronización, el comando permite reparar las asociaciones, pero habrá un intervalo con etiquetas antiguas hasta completarlo.

## Cursor, reanudación y asociaciones existentes

`--limite` debe ser positivo y `--despues-de-id` no negativo; valores inválidos terminan con `CommandError`. El cursor es exclusivo (`pk > cursor`), con orden ascendente. Cada publicación se sincroniza atómicamente; el lote completo no es una única transacción. Si se interrumpe, repetir desde el último cursor confirmado: las asociaciones ya correctas conservan sus identificadores. Un lote vacío conserva el cursor recibido. Si se usa `--solo-sin-etiquetas`, volver a recorrer desde cero cuando se incorporen huecos por debajo del cursor.

Por defecto el comando recalcula y reemplaza asociaciones distintas de las sugeridas, incluidas asociaciones añadidas manualmente. No existe procedencia manual/automática en este esquema. Usar `--solo-sin-etiquetas` para conservar cualquier asociación existente: esa condición se vuelve a comprobar bajo bloqueo, incluso si las asociaciones aparecieron después de seleccionar el lote. Esta opción no sirve para reparar etiquetas antiguas de publicaciones que ya tienen asociaciones; para ello se necesita el recálculo normal. Una repetición tras cambiar el algoritmo puede producir otras asociaciones.
