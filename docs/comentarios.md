# Comentarios de noticias

Los comentarios se presentan debajo del detalle `/noticia/<id>/`, con el estilo glass existente. Son públicos para lectura y se guardan en PostgreSQL; no dependen de almacenamiento del navegador. Esta funcionalidad no agrega valoraciones.

## Modelo y migración

`core.Comentario` enlaza `publicacion` con `Publicacion` y `autor` con `settings.AUTH_USER_MODEL` (los usuarios reales de Django). Almacena `texto` de hasta 2000 caracteres, `fecha_creacion` y `fecha_edicion` opcional. La migración `core.0008_comentario` crea la tabla nueva y depende de `0007_publicacion_imagen_archivo` y del modelo de usuario configurado.

No se modifican ni migran los modelos históricos `User`, `Role`, `VotoPublicacion` o `Auditoria`. Si se elimina una noticia, sus comentarios se eliminan por CASCADE; si se elimina una cuenta, los comentarios se conservan sin autor y se muestran como «Usuario eliminado».

## Rutas HTML y permisos

| Ruta | Método | Acceso y comportamiento |
|---|---|---|
| `/noticia/<id>/` | GET/HEAD | Lectura pública; incluye diez comentarios por página, del más reciente al más antiguo. Parámetro `pagina_comentarios`. |
| `/noticia/<id>/comentarios/` | POST | Sesión autenticada. El servidor fija autor y noticia; sólo acepta el texto del formulario. |
| `/comentarios/<id>/editar/` | GET/POST | Sólo el autor puede abrir/guardar su edición. Se conserva fecha de creación y se registra edición. |
| `/comentarios/<id>/eliminar/` | POST | Autor o usuario con `core.delete_comentario`; requiere confirmación visual previa y CSRF. GET no elimina. |

Los visitantes reciben «Ingresar para participar». Los usuarios ven Editar y Eliminar sólo en sus propios comentarios. Un administrador con permiso ve «Moderar comentario» para eliminar comentarios ajenos; no se permite reescribir el texto de otra persona en su nombre. `is_staff` por sí solo no autoriza a moderar. Los superusuarios mantienen sus permisos estándar.

`MODELOS_ADMIN` en `core/roles.py` incluye comentarios: después de la migración, ejecutar `configurar_roles` para actualizar los permisos exactos de los grupos existentes. El grupo Usuario no recibe permisos globales de edición/eliminación: las vistas comprueban propiedad del objeto. El comando sin argumentos no reasigna usuarios.

## Validación y presentación

`ComentarioForm` sólo expone `texto`; rechaza vacío, espacios o más de 2000 caracteres. No se admite HTML como marcado: Django escapa el contenido y conserva saltos de línea. No se muestran emails. Los POST inválidos conservan el texto y muestran errores en la pantalla de formulario (HTTP 400); accesos ajenos se rechazan con 403 y objetos inexistentes con 404. Los POST correctos redirigen al detalle para evitar repetición al recargar.

La confirmación de borrado usa `details` y un formulario POST con CSRF. Listado, creación, edición, confirmación y paginación no requieren JavaScript; el popup de login reutiliza el flujo de autenticación existente. Los mensajes de resultado se muestran dentro del bloque de comentarios.

## Archivos

- `app/core/models.py`, `forms.py`, `views_comentarios.py`, `urls.py` y `roles.py`.
- `views.py`: incorpora contexto paginado al detalle existente.
- `templates/partials/_comentarios.html`, `templates/core/comentario_form.html` y `templates/noticia.html`.
- `app/static/css/comments.css`.
- `app/core/migrations/0008_comentario.py` y `app/core/test_comentarios.py`.

## Pruebas y limitaciones

Ejecutar en el entorno de pruebas autorizado:

```text
docker compose exec web python manage.py test core.test_comentarios core.test_publicacion_imagen core.test_dashboard_localidades core.test_auth_views
```

Los diez casos de comentarios cubren lectura anónima y escape HTML, autenticación obligatoria, identidad fijada por servidor, límites del texto, edición/eliminación propia, rechazo de otros usuarios, moderación por grupo, rechazo a staff sin permiso, paginación, conservación tras eliminación de cuenta y CSRF. Las otras suites comprueban regresiones de imágenes, filtros y autenticación. Se usan usuarios y datos de la base de pruebas, sin cambiar noticias existentes.

La moderación inicial es eliminación; no hay revisión previa, reportes de abuso, historial de versiones ni protección antispam específica. No se afirma que esta funcionalidad cumpla por sí sola los requisitos de alertas, análisis de sentimiento, auditoría o valoraciones.

## Activación local

Con web detenido y respaldo reciente, revisar `migrate --plan`, aplicar `migrate`, ejecutar `configurar_roles`, comprobar `check` y volver a iniciar web. No borrar volúmenes. Probar después con dos cuentas normales y una administradora: lectura pública, comentario propio editable, rechazo de edición ajena y eliminación moderada.

La comprobación global `makemigrations --check --dry-run` detecta discrepancias de los IDs automáticos históricos en `PublicacionTema`, `TemaTrend`, `UserAuditoria` y `VotoPublicacion`. No propone cambios adicionales sobre Comentario; no se genera una migración ajena a esta tarea para resolver esas diferencias. Registrarlas para coordinar su revisión con el equipo.
