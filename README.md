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
├── .env.example            # plantilla de configuración (copiar a .env)
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Requisitos

- Docker Desktop con Docker Compose v2 (opción recomendada), o
- Python 3.12 o superior para desarrollo local sin Docker (Django 6.1 no
  soporta versiones anteriores). La imagen Docker usa Python 3.13.

Las dependencias están fijadas en `requirements.txt` con las versiones validadas.

## Configuración (`.env`)

Toda la configuración sensible se lee de variables de entorno; no hay claves ni
contraseñas en el código. Desde la raíz del repositorio:

```bash
cp .env.example .env            # Windows (PowerShell): Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(50))"   # pegar como SECRET_KEY
```

| Variable | Obligatoria | Uso |
|---|---|---|
| `SECRET_KEY` | Sí | Clave de Django. Sin ella la aplicación no arranca. |
| `DEBUG` | No (`False`) | `True` sólo en desarrollo. |
| `ALLOWED_HOSTS` | No (`localhost,127.0.0.1`) | Hosts separados por coma. |
| `DB_PASSWORD` | Sí con Docker | Contraseña de PostgreSQL; Compose no inicia sin ella. |
| `DB_HOST` | No | Con valor usa PostgreSQL; vacío usa SQLite (`app/db.sqlite3`). Compose lo fuerza a `db`. |
| `DB_NAME`, `DB_USER`, `DB_PORT` | No (`db`, `postgres`, `5432`) | Conexión a PostgreSQL. |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Para IA | Procesamiento con Gemini. |

`.env` está en `.gitignore` y `.dockerignore`: no se commitea ni se copia a la imagen.

> **Base existente:** PostgreSQL sólo aplica `POSTGRES_PASSWORD` al crear el
> volumen. Si ya existe `postgres_data`, `DB_PASSWORD` debe coincidir con la
> contraseña con la que se creó (antes `django_password`, fijada en Compose).

## Instalación inicial con Docker (PostgreSQL/PostGIS)

Ejecutar desde la raíz, con `.env` preparado. Compose
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

Elegir la base según `DB_HOST` en `.env`:

- **SQLite (más simple):** dejar `DB_HOST=` vacío. Se crea `app/db.sqlite3`
  (ignorado por git).
- **PostgreSQL local:** `DB_HOST=localhost` y las variables `DB_*`. Puede usarse
  la base del Compose con `docker compose up -d db` (publicada sólo en
  `127.0.0.1:5432`).

```bash
python app/manage.py migrate
python app/manage.py configurar_roles
python app/manage.py createsuperuser
python app/manage.py runserver
```

Tests:

```bash
python app/manage.py test core
```

Con SQLite, 6 tests que dependen de PostgreSQL (concurrencia e introspección de
restricciones de `PublicacionDuplicadosTestCase` y `PublicacionConcurrenciaTestCase`)
fallan; ejecutar la suite completa contra PostgreSQL
(`docker compose exec web python manage.py test core`).
No utilizar la base compartida para pruebas que escriban datos.

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

La versión validada es **Simple JWT 5.5.1**, fijada en `requirements.txt`.

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
