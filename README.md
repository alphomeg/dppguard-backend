# DPP Guard Backend

A FastAPI-based multi-tenant SaaS backend application with role-based access control (RBAC), subscription management, and tenant isolation.

## Features

- **Multi-tenancy**: Support for both Personal and Organization workspaces
- **Role-Based Access Control (RBAC)**: Global and custom roles with granular permissions
- **Subscription Management**: Plan-based feature gating and billing integration
- **User Management**: Secure authentication and user profiles
- **Invitation System**: Secure, time-bound tenant invitations
- **Database Migrations**: Alembic for schema versioning
- **Structured Logging**: Loguru-based logging with file rotation

## Tech Stack

- **Python**: 3.13+
- **Framework**: FastAPI
- **ORM**: SQLModel (SQLAlchemy + Pydantic)
- **Database**: PostgreSQL
- **Migrations**: Alembic
- **Logging**: Loguru
- **ASGI Server**: Uvicorn

## Project Structure

```
dppguard-backend/
├── app/
│   ├── api/
│   │   └── v1/
│   │       └── index.py          # API routes and endpoints
│   ├── core/
│   │   ├── config.py             # Application settings and configuration
│   │   └── logging.py            # Logging setup and configuration
│   ├── db/
│   │   ├── core.py               # Database engine and session management
│   │   └── schema.py             # SQLModel database models and schemas
│   ├── models/                   # Additional data models (if needed)
│   ├── services/                 # Business logic services
│   └── main.py                   # FastAPI application entry point
├── migrations/                   # Alembic database migrations
│   ├── env.py                    # Alembic environment configuration
│   ├── script.py.mako            # Migration script template
│   └── versions/                 # Migration version files
├── logs/                         # Application log files
├── alembic.ini                   # Alembic configuration
├── pyproject.toml                # Project dependencies and metadata
├── uv.lock                       # Dependency lock file
├── .python-version               # Python version specification
└── README.md                     # This file
```

## Prerequisites

- Python 3.13 or higher
- PostgreSQL database
- `uv` package manager (recommended) or `pip`

## Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd dppguard-backend
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv .venv
   ```

3. **Activate the virtual environment**
   - On Windows:
     ```bash
     .venv\Scripts\activate
     ```
   - On Linux/Mac:
     ```bash
     source .venv/bin/activate
     ```

4. **Install dependencies**
   
   Using `uv` (recommended):
   ```bash
   uv sync
   ```
   
   Or using `pip`:
   ```bash
   pip install -e .
   ```

5. **Set up environment variables**
   
   Create a `.env` file in the project root:
   ```env
   DATABASE_URL=postgresql://user:password@localhost:5432/dppguard
   DEBUG=False
   HOST=127.0.0.1
   PORT=8000
   APP_NAME=DPP Guard API
   ```

6. **Set up the database**
   
   Create a PostgreSQL database:
   ```sql
   CREATE DATABASE dppguard;
   ```

7. **Run database migrations**
   ```bash
   alembic upgrade head
   ```

## Running the Application

### Development Server

Run the application using Python:
```bash
python -m app.main
```

Or using Uvicorn directly:
```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The API will be available at:
- **API**: http://127.0.0.1:8000
- **Interactive API Docs (Swagger UI)**: http://127.0.0.1:8000/docs
- **Alternative API Docs (ReDoc)**: http://127.0.0.1:8000/redoc

### Production Server

For production, use a production ASGI server like Gunicorn with Uvicorn workers:
```bash
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

## Database Migrations

### Create a new migration
```bash
alembic revision --autogenerate -m "Description of changes"
```

### Apply migrations
```bash
alembic upgrade head
```

### Rollback migrations
```bash
alembic downgrade -1
```

### View migration history
```bash
alembic history
```

## API Endpoints

### Health Check
- `GET /api/v1/` - API status check
- `GET /api/v1/readiness` - Readiness probe (checks database connectivity)

## Configuration

The application configuration is managed through environment variables and the `Settings` class in `app/core/config.py`. Key settings include:

- `DATABASE_URL`: PostgreSQL connection string
- `DEBUG`: Enable/disable debug mode
- `HOST`: Server host address
- `PORT`: Server port number
- `APP_NAME`: Application name

## Logging

Logs are written to:
- **Console**: Standard output
- **File**: `logs/application.log` (with rotation at 500MB and compression)

Log levels and formatting are configured in `app/core/logging.py`.