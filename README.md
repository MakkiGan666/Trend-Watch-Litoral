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

## Opción A: con Docker (PostgreSQL/PostGIS)

```bash
docker compose up --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

Abrir http://localhost:8000

## Opción B: local, sin Docker (SQLite)

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cd app
python manage.py migrate
python manage.py runserver
```

`settings.py` usa PostgreSQL si existe la variable `DB_HOST` (Docker la define)
y SQLite en caso contrario.

## Rutas

| URL            | Vista        |
|----------------|--------------|
| `/`            | inicio       |
| `/categorias/` | categorías   |
| `/litoral/`    | mapa Litoral |
| `/login/`      | login        |
| `/dashboard/`  | publicaciones (datos reales de la BD) |
| `/admin/`      | admin Django |

## Roles y permisos

La autenticación utiliza usuarios Django, sesiones para el sitio y JWT para la
API. Las consultas públicas de noticias se mantienen públicas. El dashboard
requiere `core.view_publicacion`.

Después de aplicar las migraciones, configurar los grupos:

```bash
docker compose exec web python manage.py migrate
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
