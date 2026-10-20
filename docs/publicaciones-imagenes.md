# Imágenes de publicaciones

El formulario compartido de nueva publicación y edición acepta un archivo del dispositivo (PC o móvil) y una URL externa opcional. Requiere permisos de creación/edición existentes y conserva CSRF. El formulario envía `multipart/form-data` y las vistas reciben `request.FILES`.

- Archivos admitidos: JPEG, PNG y WebP de hasta 5 MB. `ImageField` verifica el contenido; no basta con el nombre o MIME declarado.
- Los archivos válidos se guardan con nombre UUID y extensión derivada del formato, en `MEDIA_ROOT/publicaciones/`.
- Migración `core.0007_publicacion_imagen_archivo`: agrega un campo opcional a `Publicacion`, sin cambiar las URLs existentes.
- `imagen_publica_url` prioriza el archivo subido; si no existe, devuelve `imagen_url`. Las respuestas del listado general y de localidades conservan el campo JSON `imagen_url` con la URL efectiva. El detalle también usa esa imagen.
- Editar permite conservar, reemplazar o quitar la imagen mediante el control de Django. Quitar el archivo asociado vuelve a mostrar la URL externa si hay una; para dejar la noticia sin imagen deben quedar ambos campos vacíos.
- Cambiar únicamente la imagen no vuelve a ejecutar el análisis de sentimiento. Se conserva el circuito de permisos, duplicados y transacciones existente.

## Almacenamiento y entorno

En desarrollo: `MEDIA_ROOT = BASE_DIR / 'media'`, `MEDIA_URL = '/media/'`. El Compose actual monta `./app:/app`, por lo que los archivos quedan en `app/media/` del equipo anfitrión y sobreviven al reinicio/recreación del contenedor. La carpeta está excluida de Git y del contexto de construcción Docker.

Las imágenes cargadas se consideran públicas, como las noticias. La ruta de desarrollo se habilita mediante `static()` de Django cuando `DEBUG=True`. En producción debe configurarse un servidor o almacenamiento de medios; no usar el servidor de desarrollo como despliegue. No hace falta instalar una dependencia nueva en la imagen actual: Pillow está disponible y se comprueba en las pruebas.

Respaldar también `app/media/`: el respaldo de PostgreSQL contiene referencias a archivos, no sus bytes. Django no elimina automáticamente archivos reemplazados o desasociados ni revierte escrituras de almacenamiento con transacciones SQL; una futura limpieza debe revisar referencias y respaldos, sin eliminar archivos de forma automática desde esta funcionalidad.

## Verificación

`docker compose exec web python manage.py test core.test_publicacion_imagen`

La suite usa una base de pruebas y una carpeta temporal. Cubre URL externa, creación sin imagen, URL inválida, archivo guardado/expuesto en listado y detalle, conservación/reemplazo/desasociación y rechazo de archivo falso o mayor de 5 MB.

Después de revisar/aplicar la migración, iniciar sesión como administrador, abrir Nueva publicación, seleccionar una imagen y guardar una noticia de prueba autorizada. Comprobar la tarjeta y el detalle. En móvil el selector lo proporciona el navegador/sistema operativo; no se obliga a usar la cámara. La disponibilidad de formatos y proveedores depende del dispositivo; HEIC no está admitido por este formulario.
