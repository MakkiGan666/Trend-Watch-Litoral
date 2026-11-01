# Propuesta de PR hacia main

Título: `feat(admin): permitir crear administradores desde el panel de TrendWatch`

## Descripción

Permite que un administrador cree otra cuenta del mismo rol desde Publicaciones o Dashboard → Gestión de administradores, con usuario, correo y contraseña confirmada. La cuenta creada puede iniciar sesión y crear otros administradores.

El backend exige los permisos del panel más `auth.add_user`, asigna exclusivamente el grupo Administrador y reutiliza las validaciones y el bloqueo de identidad existentes. Las contraseñas usan validadores y hash de Django; el formulario conserva CSRF. El alta y su evento `LogEntry` se guardan en una transacción, sin registrar secretos.

Dashboard e indicadores usan los permisos del panel para igualar las funciones del rol. No se otorga superusuario ni acceso administrativo a tokens JWT; esos privilegios técnicos permanecen reservados a superusuarios. No hay migraciones, dependencias ni cambios de Compose.

## Validación

- 54 pruebas dirigidas aprobadas y una adicional de equivalencia de permisos aprobada, con PostgreSQL aislado.
- Prueba adicional de restricción JWT aprobada: GET/POST devuelven 403 a administradores existentes y nuevos; el superusuario mantiene acceso. Total: 56 pruebas dirigidas distintas aprobadas, reutilizando evidencia sin cambios de código de producción.
- Suite completa comparada: main 407 tests y rama 416 en esa ejecución; ambas con los mismos 10 fallos, un error y una omisión. Los bloques coinciden al normalizar las fechas de captura.
- Fallos preexistentes en ingesta/clasificación y cuatro subcasos de actualización de publicaciones por los campos derivados del buscador.
- Checks Django sin incidencias y `git diff --check` correcto. La comprobación de migraciones detecta los mismos cuatro ajustes de claves automáticas ya presentes en main; no se generaron ni aplicaron.

Capturas: [escritorio](capturas/administradores/escritorio.png) y [móvil](capturas/administradores/movil.png). Alcance de auditoría, instrucciones y evidencia: [gestion-administradores.md](gestion-administradores.md).

## Límites conocidos

El grupo Administrador debe estar configurado con sus permisos canónicos. La auditoría general futura deberá integrar los eventos de LogEntry y definir retención/protección. La suite global mantiene los fallos preexistentes documentados; esta propuesta no los corrige.
