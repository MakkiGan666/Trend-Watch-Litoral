# Recuperación de imágenes

`python manage.py recuperar_imagenes` consulta hasta diez noticias de la fuente Policiales sin imagen, usando el transporte HTTPS validado del medio. Lee los metadatos originales sin ingesta ni IA. La ejecución por defecto simula; `--aplicar` actualiza únicamente `imagen_url` si sigue vacía y no apareció una imagen manual. `--limite` admite entre 1 y 100.

```powershell
docker compose exec web python manage.py recuperar_imagenes --aplicar
```

No crea publicaciones, cambia contenidos ni reemplaza imágenes existentes. Los enlaces sin foto o no disponibles quedan informados y pueden reintentarse. Los datos recuperados pertenecen a cada base local; el commit contiene el comando, no las noticias.


Para recorrer más de un lote, usar `--despues-de-id=N` con el cursor informado al final de la ejecución y conservar el límite y modo elegidos. El límite cuenta intentos, incluso sin imagen o con error HTTP; el cursor avanza en ambos casos. Por ejemplo, tras un lote cuyo cursor sea 123:

```powershell
docker compose exec web python manage.py recuperar_imagenes --limite=100 --despues-de-id=123
```

La salida indica si quedan candidatos o se llegó al fin del conjunto. Sin cursor se empieza desde el principio, lo que permite reintentar pendientes. El cursor no se guarda en la base: una simulación no modifica registros; para aplicar luego todo lo simulado, comenzar nuevamente sin cursor con `--aplicar`. Los errores esperados de transporte y protocolo HTTP se informan por publicación y se continúa con las siguientes. Los errores de programación o persistencia se propagan.
