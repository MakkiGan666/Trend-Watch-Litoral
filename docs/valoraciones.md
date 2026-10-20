# Valoraciones de lectores

En el detalle de una noticia, encima de los comentarios, aparece «¿Qué sentimiento te genera esta noticia?» con Positivo, Neutral y Negativo. Es una respuesta de los usuarios, independiente del análisis automático del contenido.

## Persistencia

`ValoracionPublicacion` relaciona `Publicacion` con `settings.AUTH_USER_MODEL`, almacena el sentimiento y fechas de creación/actualización. La migración `core.0009_valoracionpublicacion` crea la tabla con:

- Unicidad de `(publicacion, usuario)`.
- Restricción que admite únicamente `positivo`, `neutral` y `negativo`.

No se modifican `Sentimiento` (análisis de IA/local) ni el modelo histórico `VotoPublicacion`, que apunta a otro modelo de usuario. No se trasladan votos antiguos: dos opciones históricas no se pueden convertir automáticamente en tres sentimientos. Ausencia de valoración no significa Neutral.

Al eliminar una noticia o una cuenta se eliminan sus valoraciones mediante CASCADE. Los totales siempre se calculan de los registros actuales de la noticia, sin contadores almacenados en el navegador ni valores de ejemplo.

## Acceso y acciones

- Lectura pública del total y de los tres conteos; no se publica qué eligieron otros usuarios.
- POST `/noticia/<id>/valoracion/` (`valorar_noticia`): sesión y CSRF obligatorios. GET no modifica datos.
- El formulario admite `sentimiento=positivo|neutral|negativo|retirar`. Un valor inválido responde 400; una noticia inexistente, 404.
- La identidad se toma exclusivamente de `request.user`. Campos enviados como `usuario` no permiten operar sobre otra cuenta, ni siquiera a un administrador.
- Seleccionar otro sentimiento actualiza el registro propio. Repetir el mismo mantiene un solo registro. «Retirar mi valoración» elimina sólo la propia; repetir el retiro es válido.
- Los cambios y retiros toman bloqueo transaccional de la publicación para serializar operaciones concurrentes. La restricción de unicidad evita duplicados a nivel de base.
- Tras un POST válido se redirige al detalle con ancla `#valoraciones`; recargar no repite el envío.

La interfaz usa formularios HTML y CSS glass; no requiere JavaScript para guardar. Los visitantes ven resultados y un enlace al login. La opción propia muestra «Tu elección», `aria-pressed=true` y posibilidad de retirada. No se modifican los roles de comentarios o Dashboard.

## Archivos

`models.py`, `migrations/0009_valoracionpublicacion.py`, `views_valoraciones.py`, `urls.py` y contexto del detalle en `views.py`; `templates/partials/_valoraciones.html`, `templates/noticia.html`, `app/static/css/news-ratings.css` y `test_valoraciones.py`.

## Activación y comprobación

Con respaldo reciente y web detenido: aplicar la migración `0009`, ejecutar `check` y reiniciar web. La tabla debe existir antes de abrir un detalle con el código nuevo. No se necesita reconfigurar roles para valorar: el acceso es la sesión propia, sin permisos globales de modificar valoraciones ajenas.

Pruebas aisladas:

```text
docker compose exec web python manage.py test core.test_valoraciones core.test_comentarios core.test_publicacion_imagen core.test_dashboard_localidades core.test_auth_views
```

Los siete casos de valoraciones verifican totales públicos, ausencia distinta de Neutral, autenticación/CSRF/métodos, creación y cambios sin duplicados, retiro idempotente, identidad y separación de IA, validación, restricciones de base y aislamiento entre noticias. El bloqueo concurrente está implementado; esta suite no incluye una prueba de carrera con conexiones simultáneas.

Comprobación manual con cuentas autorizadas: leer sin sesión, elegir Positivo, cambiar a Neutral, retirar y revisar los tres totales; repetir con una segunda cuenta. No interpretar estos conteos como sentimiento automático, relevancia ni muestra representativa de toda la población.
