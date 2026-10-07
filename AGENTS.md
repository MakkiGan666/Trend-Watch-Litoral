# Repository Guidelines

## Project Structure & Module Organization

TrendWatch Litoral combines Django with server-rendered templates and vanilla JavaScript. `app/manage.py` is the management entry point; `app/mi_proyecto/` contains settings and project routes. `app/core/` holds models, forms, serializers, views, migrations, and tests. Ingestion and sentiment processing live in `core/services/`, `core/scrapers/`, and `core/management/commands/`.

Templates live in `app/core/templates/`, with reusable fragments in `partials/`. Served CSS, JavaScript, and images belong in `app/static/`. `docs/` contains mockups and a JSX prototype; `drawio/` stores diagrams. These are reference materials rather than served assets.

## Build, Test, and Development Commands

Run these commands from the repository root:

- `docker compose up --build`: build and start Django with PostgreSQL/PostGIS at `http://localhost:8000`.
- `docker compose exec web python manage.py migrate`: apply database migrations.
- `docker compose exec web python manage.py createsuperuser`: create an administrator.
- `docker compose exec web python manage.py check`: check Django configuration.
- `docker compose exec web python manage.py test core`: run core tests.
- `docker compose exec web python manage.py makemigrations core`: generate migrations after model changes.

For local development, install `requirements.txt` in a virtual environment and configure `DB_HOST` and related database variables before running `python app/manage.py runserver`. The README describes a SQLite fallback, but current settings do not implement it.

## Coding Style & Naming Conventions

Use four spaces in Python, `snake_case` for functions and variables, and `PascalCase` for classes. Follow adjacent frontend formatting; shared JavaScript uses two-space indentation. Reuse template partials and keep external-service logic in service modules. No formatter or linter configuration is provided.

## Testing Guidelines

Use Django `TestCase` in `app/core/tests.py`, with methods named `test_<behavior>`. Cover changed model, authentication, and ingestion behavior; mock external news and Gemini calls. No coverage threshold is configured. Root-level `test_ingesta.py` is a manual HTTP smoke script requiring a running server and local credentials; it creates a publication.

## Commit & Pull Request Guidelines

History mixes informal Spanish messages with `feat(scope): ...` and `fix(scope): ...`; prefer the scoped format. PRs should describe changed behavior, link relevant issues, and report validation commands and results. Include screenshots for interface changes and note migrations or configuration changes.

## Security & Configuration

Configure `GEMINI_API_KEY` for AI processing and use local-only credentials for manual smoke tests.

## Agent-Specific Instructions

- Before changes, inspect relevant existing code and understand its integration with the project.
- Modify only files related to the requested task.
- Delete or substantially rewrite another contributor's code only when necessary for the task; explain why beforehand.
- Never modify, expose, or commit `.env` files, API keys, passwords, tokens, or other credentials.
- Before database schema changes, explain the affected models and migrations.
- Preserve compatibility with the existing Docker Compose development environment.
- Prefer small, focused changes; avoid large refactors unless explicitly requested.
- After Python/Django changes, run appropriate Django checks or tests when possible.
- Obtain explicit confirmation before destructive database, Docker, Git, or filesystem commands.
- Do not commit, push, merge, rebase, reset, or otherwise alter Git history unless explicitly requested.
- Before a large change spanning multiple files, briefly explain the approach and affected files.
- Preserve existing Spanish domain terminology and naming conventions, such as `Publicacion`.
