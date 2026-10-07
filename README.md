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

El comando reutiliza los grupos `Lector`, `Analista` y `Administrador` y reemplaza
sus permisos por el conjunto definido en `core/roles.py`. Puede ejecutarse varias
veces. No asigna usuarios salvo que se indiquen ambas opciones:

```bash
docker compose exec web python manage.py configurar_roles --usuario nombre_usuario --rol Analista
```

La asignación explícita reemplaza los grupos y permisos individuales del usuario.
Sólo Administrador recibe `is_staff`; el comando no reasigna superusuarios.
Usar este comando para altas/cambios de rol y mantener un único rol por cuenta.
Los permisos Django son acumulativos: permisos individuales u otros grupos pueden
ampliar el acceso. Los superusuarios conservan sus privilegios estándar.

Lector puede leer; Analista también puede crear, editar, ejecutar scraping e IA;
Administrador también puede eliminar y administrar usuarios/grupos en Django
Admin. El acceso al Admin utiliza el mecanismo estándar de Django: usuario
activo con `is_staff`, y permisos de modelo para cada operación. Mantener
`is_staff=False` en Lector y Analista; el comando de asignación lo establece.

No cargar la fixture histórica `core/fixtures/roles.json` para configurar estos
roles: usa IDs de permisos y contiene el conjunto anterior de Analista. Usar
`configurar_roles` después de `migrate`.

Scraping e IA por HTTP requieren POST. La API sigue requiriendo JWT; una sesión
web no reemplaza el token. Los comandos de scraping de terminal son operaciones
del servidor y su acceso depende de los permisos operativos de Docker/servidor.
