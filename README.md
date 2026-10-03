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
