# Django Web App — Coding Instructions

## Project overview

This is a Django web application for managing industrial activities and resources across multiple plants. It uses PostgreSQL as the database and Django's built-in ORM and admin panel.

## Stack

- **Backend**: Django
- **Database**: PostgreSQL via psycopg2
- **ORM**: Django ORM
- **Environment**: python-dotenv

## Project structure

```
progetto/
├── .env
├── manage.py
├── config/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── core/
│   ├── models.py
│   ├── views.py
│   ├── urls.py
│   ├── admin.py
│   └── templates/
└── code_template/   ← REFERENCE ONLY, not part of the project
```

> **`code_template/`** contains legacy code (SQLite SQL, old VBA/Access logic) used only as reference to understand the original data structures when designing the new Django solution. Do not treat anything in `code_template/` as current implementation — never import from it or replicate it directly.

## Database

PostgreSQL database named `gestione_attivita`. Connection credentials are stored in `.env` and loaded via `python-dotenv` in `settings.py`. Never hardcode credentials.

```env
DB_PASSWORD=your_password
```

### Tables

- `stabilimenti` — plants/locations
- `responsabili` — responsible persons, linked to a plant
- `attivita` — activities, linked to a responsible and a plant. Unique constraint on `(commessa, progressivo)`
- `mandrini`, `tastatori`, `maschere`, `teste`, `generatori` — resources, each linked to a plant. Primary key is a string (e.g. `M1`) engraved on the physical component

## Code style

- Follow PEP8
- Use snake_case for variables, functions, and file names
- Use PascalCase for class names
- Keep views thin — business logic goes in separate service functions or model methods
- Never put raw SQL in views — use the Django ORM
- All strings must be in Italian (UI, labels, error messages). Code and comments in English

## Models

- All models live in `core/models.py`
- Resource models (`Mandrino`, `Tastatore`, `Maschera`, `Testa`, `Generatore`) use `CharField` as primary key — never auto-increment
- Foreign keys to `Stabilimento` use `on_delete=models.RESTRICT`
- Foreign key from `Responsabile` to `Stabilimento` uses `on_delete=models.SET_NULL, null=True`
- `Attivita.data_reale_inizio` and `Attivita.data_reale_fine` are always nullable

## Migrations

- Always run `python manage.py makemigrations` and `python manage.py migrate` after changing models
- Never edit migration files manually
- Since tables already exist in the database, use `managed = False` in models or run `inspectdb` to reflect existing tables

## Django admin

- Register all models in `core/admin.py`
- Use `list_display`, `list_filter`, and `search_fields` for all models
- The admin panel is the primary management interface — keep it clean and usable

## Environment

- Load `.env` at the top of `settings.py` with `load_dotenv()`
- Never commit `.env` to version control
- Always add `.env` to `.gitignore`

## Running the project

```bash
python manage.py runserver
```

## Running tests

```bash
python manage.py test
```
