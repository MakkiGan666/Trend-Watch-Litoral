# Recuperación de imágenes

`python manage.py recuperar_imagenes` consulta hasta diez noticias de la fuente Policiales sin imagen, usando el transporte HTTPS validado del medio. Lee los metadatos originales sin ingesta ni IA. La ejecución por defecto simula; `--aplicar` actualiza únicamente `imagen_url` si sigue vacía y no apareció una imagen manual. `--limite` admite entre 1 y 100.

```powershell
docker compose exec web python manage.py recuperar_imagenes --aplicar
```

No crea publicaciones, cambia contenidos ni reemplaza imágenes existentes. Los enlaces sin foto o no disponibles quedan informados y pueden reintentarse. Los datos recuperados pertenecen a cada base local; el commit contiene el comando, no las noticias.
