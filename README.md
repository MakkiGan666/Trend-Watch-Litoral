# TrendWatch Litoral

Proyecto unificado (backend + frontend) en un solo repositorio.

## Estructura

```
trendwatch-litoral/
├── app/
│   ├── manage.py
│   ├── mi_proyecto/        # settings, urls, wsgi/asgi
│   ├── core/               # models, views, urls, migrations
│   │   └── templates/      # base, inicio, categorias, litoral, login, core/dashboard
│   └── static/             # css/, js/, mockup/ (fondos de departamentos)
├── docs/                   # mockups y prototipos (no se sirven en la web)
├── drawio/                 # diagrama entidad-relación
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Instalación inicial con Docker (PostgreSQL/PostGIS)

Ejecutar desde la raíz, con la configuración de entorno preparada. Compose
monta `./app` en `/app`; los comandos puntuales siguientes sustituyen `runserver`
y no publican los puertos de web. Iniciar sólo la base y aplicar las migraciones
antes de habilitar web para atender tráfico:

```bash
docker compose build web
docker compose up -d db
docker compose run --rm --no-deps web python manage.py migrate
docker compose run --rm --no-deps web python manage.py showmigrations token_blacklist
docker compose run --rm --no-deps web python manage.py check
docker compose up -d web
docker compose exec web python manage.py createsuperuser
```

Esperar a que `db` esté saludable antes de ejecutar los comandos puntuales;
puede comprobarse con `docker compose ps`. No iniciar web si falla una migración
o quedan migraciones de blacklist sin aplicar. Abrir http://localhost:8000.

### Despliegue sobre una base existente

Antes de ejecutar migraciones sobre PostgreSQL compartido, obtener autorización
explícita del equipo, coordinar una ventana sin tráfico y realizar un respaldo
de la base. Ejecutar
`docker compose stop web` **antes de actualizar el código montado**, ya que Compose
utiliza un volumen del repositorio. Este paso no detiene `db`.
Con la versión nueva disponible, conservar la base existente y ejecutar:

```bash
docker compose build web
docker compose run --rm --no-deps web python manage.py migrate --plan
docker compose run --rm --no-deps web python manage.py migrate
docker compose run --rm --no-deps web python manage.py showmigrations token_blacklist
docker compose run --rm --no-deps web python manage.py check
docker compose up -d web
```

Revisar el plan antes de aplicar migraciones. `db` debe estar disponible durante
todo el procedimiento. Aplicar la cadena oficial de `token_blacklist` incluida
en la dependencia antes de iniciar web con la nueva configuración; PR4 no agrega
migraciones propias ni requiere `makemigrations`. No recrear volúmenes ni
reconfigurar roles como parte de esta actualización.

Después de habilitar web, comprobar login, refresh, rechazo del refresh anterior
y logout con cuentas de prueba autorizadas. Conservar las tablas ante un rollback:
volver a código que ignore blacklist dejaría de respetar esas revocaciones.

Estos comandos corresponden al Compose de desarrollo del repositorio, que usa
`runserver`; adaptar el control de tráfico al entorno de despliegue real.

### Desarrollo local sin Docker

Desde la raíz del repositorio, crear y activar un entorno virtual e instalar
las dependencias:

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Preparar también PostgreSQL/PostGIS para desarrollo local.
La configuración actual define PostgreSQL cuando está presente `DB_HOST`; no
define una base SQLite cuando falta esa variable. Para ejecutar
`python app/manage.py migrate` o `runserver` localmente,
preparar las dependencias y una base de desarrollo con las variables `DB_*`
correspondientes. No utilizar la base compartida para pruebas que escriban datos.
La validación aislada con SQLite requiere una configuración específica desde el
arranque de Django, distinta de la configuración habitual.

## Rutas

| URL            | Vista        |
|----------------|--------------|
| `/`            | inicio       |
| `/categorias/` | categorías   |
| `/litoral/`    | mapa Litoral |
| `/login/`      | login        |
| `/dashboard/`  | publicaciones (datos reales de la BD) |
| `/admin/`      | admin Django |

## Autenticación HTML y JWT (PR4)

El login HTML y JWT acepta username **o** email con contraseña. Se recortan sólo
los espacios exteriores del identificador; la contraseña se conserva exactamente.
Username se compara de forma exacta y email sin distinguir mayúsculas/minúsculas.
Si el identificador corresponde a varias cuentas distintas, incluidas inactivas,
se rechaza sin elegir una cuenta. Credenciales incorrectas, cuentas inexistentes,
inactivas o identificadores ambiguos reciben un error genérico.

La versión validada es **Simple JWT 5.5.1**. `requirements.txt` no fija esa versión;
una instalación nueva debe comprobar las versiones efectivas antes de asumir la
misma compatibilidad.

### Endpoints JWT

Enviar cuerpos JSON. Para los endpoints protegidos, usar
`Authorization: Bearer <access>`. Una sesión HTML no sustituye esa autenticación.

| Método y ruta | Autenticación requerida | Entrada | Respuesta |
|---|---|---|---|
| `POST /api/auth/login/` | Ninguna | `username`: string con username o email; `password`: string | `200`: `access` y `refresh`; `400`: campos inválidos/ausentes; `401`: credenciales rechazadas |
| `POST /api/auth/refresh/` | Refresh válido en el cuerpo; no requiere access | `refresh` | `200`: `access` y nuevo `refresh`; `400`: campos inválidos/ausentes; `401`: token inválido, vencido, revocado o cuenta eliminada/inactiva |
| `GET /api/auth/me/` | Access válido | Sin cuerpo | `200`: perfil propio; `401`: autenticación ausente o rechazada |
| `POST /api/auth/logout/` | Access válido | `refresh`: string no vacío, perteneciente a la misma cuenta | `204`: sin contenido; `400`: payload inválido o refresh inválido/vencido/revocado; `401`: autenticación ausente o rechazada; `403`: refresh ajeno, sin revocarlo |

`/api/auth/me/` devuelve `id`, `username`, `email`, `first_name`, `last_name`,
`is_staff`, `is_superuser` y `roles`. `GET /api/auth/logout/` autenticado devuelve
`405`. No hay un endpoint público de verificación de tokens configurado.

### Rotación, blacklist y logout

El access dura 60 minutos y el refresh un día. Cada renovación correcta genera
un nuevo refresh y agrega el anterior a blacklist: el cliente debe guardar el
refresh nuevo y descartar el anterior. Reutilizar secuencialmente el anterior
devuelve `401`. La rotación secuencial está validada; no hay una garantía adicional
de exclusión entre renovaciones concurrentes. El cliente debe evitar solicitudes
simultáneas de renovación.

El logout HTML (`/logout/`, actualmente mediante GET) limpia la sesión Django y
redirige al inicio. El logout JWT requiere POST y revoca únicamente el refresh
presentado; no cierra sesiones HTML ni revoca otros refresh de la cuenta. Repetir
logout con el mismo refresh revocado devuelve `400`.

Los access ya emitidos conservan su vigencia restante, sujetos a las comprobaciones
habituales de autenticación. Logout JWT no incorpora revocación global de access.
El cliente debe eliminar sus tokens locales al cerrar sesión.

### Mantenimiento de blacklist

Programar diariamente, en el entorno autorizado, la limpieza oficial de registros
vencidos. Con web activo en este Compose:

```bash
docker compose exec web python manage.py flushexpiredtokens
```

La limpieza elimina registros vencidos de outstanding y blacklist. Las tablas
almacenan tokens y referencias a usuarios: restringir el acceso a la base,
administración y respaldos; no copiar tokens a logs, reportes o ejemplos públicos.
No borrar registros vigentes de blacklist, porque se perdería su revocación.

## Roles y permisos

La autenticación utiliza usuarios Django, sesiones para el sitio y JWT para la
API. Las consultas públicas de noticias se mantienen públicas. El dashboard
requiere `core.view_publicacion`.

Después de completar el procedimiento seguro de migraciones de
[instalación inicial](#instalación-inicial-con-docker-postgresqlpostgis) o
[despliegue sobre una base existente](#despliegue-sobre-una-base-existente),
configurar los grupos cuando corresponda:

```bash
docker compose exec web python manage.py configurar_roles
```

El comando crea/reutiliza únicamente los roles activos `Usuario` y
`Administrador`, con los permisos exactos definidos en `core/roles.py`.
Es idempotente. Usuario sólo puede consultar noticias y dashboard;
Administrador puede además crear, editar, eliminar, ejecutar scraping e IA y
administrar usuarios/grupos en Django Admin.

La asignación explícita reemplaza grupos y limpia permisos individuales:

```bash
docker compose exec web python manage.py configurar_roles --usuario nombre_usuario --rol Usuario
```

Usuario recibe `is_staff=False`; Administrador recibe `is_staff=True`.
El comando no reasigna superusuarios. El Admin conserva el mecanismo estándar
Django: cuenta activa con `is_staff` y permisos por modelo. Mantener un único rol
por cuenta y no conceder permisos individuales ni staff a Usuario.
Los permisos Django son acumulativos; los superusuarios conservan sus privilegios.

### Grupos históricos

`Lector` y `Analista` quedan fuera de `PERMISOS_ROLES` y no aparecen como roles
en `/api/auth/me/`. Su existencia no impide ejecutar `configurar_roles`.
El comando no modifica esos grupos, sus permisos, membresías ni flags de usuarios.
No realiza migraciones o limpieza de datos históricos.

Al asignar explícitamente Usuario o Administrador, se reemplazan los grupos y
permisos individuales únicamente de esa cuenta, ajustando también `is_staff`.
Los permisos de grupos históricos conservan su efecto en Django aunque no se
muestren como roles: revisar esas cuentas por separado si se requiere retirar
accesos anteriores.

No cargar la fixture histórica `core/fixtures/roles.json` para configurar estos
roles: usa IDs de permisos y contiene el conjunto anterior de Analista. Usar
`configurar_roles` después de `migrate`.

Scraping e IA por HTTP requieren POST. La API sigue requiriendo JWT; una sesión
web no reemplaza el token. Los comandos de scraping de terminal son operaciones
del servidor y su acceso depende de los permisos operativos de Docker/servidor.
