# Etiquetas navegables de noticias

Cada publicación puede tener hasta 15 etiquetas ordenadas. En la lista de una categoría se muestran las primeras cinco; en el detalle se muestran todas. Cada etiqueta enlaza a `/etiquetas/<slug>/`, una lista paginada de publicaciones con esa misma etiqueta. Desde cualquiera de esas noticias se puede seguir otra etiqueta.

Las etiquetas se extraen de forma determinista del título y del contenido. No se llama a servicios de IA ni se calcula el resultado en cada visita. Al crear o editar título o contenido, las asociaciones se actualizan. Las noticias anteriores requieren el comando de carga.

Después de `python manage.py migrate`, ejecutar por lotes:

```text
python manage.py generar_etiquetas --limite=200
python manage.py generar_etiquetas --despues-de-id=<cursor impreso> --limite=200
```

Repetir con el cursor impreso hasta que el comando indique `Publicaciones procesadas: 0`. El comando recalcula el lote de forma segura, por lo que un lote puede repetirse si se interrumpe. Revisar una muestra de etiquetas antes de completar todo el archivo; el método léxico puede escoger expresiones poco útiles en algunas noticias.
