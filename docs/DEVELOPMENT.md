# Shizuha Notes Development Guide

## Prerequisites

- Docker and Docker Compose
- Node.js 20+ (for local frontend development)
- Python 3.10+ (for local backend development)

## Project Structure

```
shizuha-notes/
├── notesmanager/          # Django project settings
│   ├── settings.py        # Django configuration
│   ├── urls.py            # Root URL configuration
│   ├── celery.py          # Celery app configuration
│   └── middleware.py      # Custom middleware
├── notes/                 # Main Django app
│   ├── models.py          # Data models
│   ├── views.py           # API ViewSets
│   ├── serializers.py     # DRF serializers
│   ├── authentication.py  # FederatedUser auth
│   ├── permissions.py     # Access control
│   ├── urls.py            # API routes
│   ├── admin.py           # Django admin
│   └── services/          # Business logic
├── frontend/              # React Vite app
│   └── src/
│       ├── components/    # React components
│       ├── pages/         # Page components
│       ├── contexts/      # React contexts
│       ├── services/      # API client
│       └── hooks/         # Custom hooks
├── docs/                  # Documentation
├── Dockerfile             # Backend container
├── supervisord.conf       # Process manager
└── requirements.txt       # Python dependencies
```

## Running the Service

### With Docker Compose (Recommended)

```bash
# From shizuha-stack root
docker compose up shizuha-notes shizuha-notes-frontend

# Run migrations (if needed)
docker compose exec shizuha-notes python manage.py migrate

# Create superuser
docker compose exec shizuha-notes python manage.py createsuperuser

# Access the app
# Frontend: http://localhost:8002/notes/
# API: http://localhost:8002/shizuha-notes/api/
# Admin: http://localhost:8002/shizuha-notes/admin/
```

### Local Development

#### Backend

```bash
cd shizuha-notes

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DEBUG=True
export JWT_SECRET_KEY=your-secret-key
export POSTGRES_HOST=localhost
export POSTGRES_DB=shizuha_notes

# Run migrations
python manage.py migrate

# Run development server
python manage.py runserver 8012
```

#### Frontend

```bash
cd shizuha-notes/frontend

# Install dependencies
npm install

# Run development server
npm run dev
```

## Testing

### Backend Tests

```bash
# Run all tests
docker compose exec shizuha-notes python manage.py test

# Run specific app tests
docker compose exec shizuha-notes python manage.py test notes

# Run with coverage
docker compose exec shizuha-notes coverage run manage.py test
docker compose exec shizuha-notes coverage report
```

### Frontend Tests

```bash
cd shizuha-notes/frontend

# Run tests
npm test

# Run with coverage
npm run test:coverage
```

### E2E Tests (Playwright)

```bash
cd shizuha-notes/e2e

# Install dependencies
npm install

# Run tests
npm test

# Run tests with UI
npm run test:ui

# Run tests in headed mode
npm run test:headed
```

## Code Style

### Backend

- Follow PEP 8 guidelines
- Use Black for code formatting
- Use isort for import sorting

```bash
# Format code
black .
isort .
```

### Frontend

- Follow ESLint configuration
- Use Prettier for formatting

```bash
# Lint code
npm run lint

# Format code
npm run format
```

## Database

### Migrations

```bash
# Create migrations
docker compose exec shizuha-notes python manage.py makemigrations

# Apply migrations
docker compose exec shizuha-notes python manage.py migrate

# Show migration status
docker compose exec shizuha-notes python manage.py showmigrations
```

### Rebuild Search Index

```bash
# Rebuild full-text search index
docker compose exec shizuha-notes python manage.py rebuild_search_index
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | `True` | Django debug mode |
| `SECRET_KEY` | - | Django secret key |
| `JWT_SECRET_KEY` | - | Shared JWT secret with Shizuha ID |
| `POSTGRES_DB` | `shizuha_notes` | Database name |
| `POSTGRES_USER` | `shizuha` | Database user |
| `POSTGRES_PASSWORD` | `shizuha` | Database password |
| `POSTGRES_HOST` | `shizuha-db` | PostgreSQL host |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `CELERY_BROKER_URL` | `redis://redis:6379/4` | Celery broker |
| `SHIZUHA_ID_API_URL` | `http://shizuha-id:8001/api` | Shizuha ID service |
| `MAX_ATTACHMENT_SIZE` | `52428800` | Max upload size (50MB) |

## API Documentation

API documentation is available at:
- Swagger UI: `http://localhost:8002/shizuha-notes/api/docs/`
- ReDoc: `http://localhost:8002/shizuha-notes/api/redoc/`

## Troubleshooting

### Container not starting

The image compiles dependency and application bytecode during its build. Keep
`--compile-bytecode` on both uv installation commands and the application
`compileall` step: runtime `PYTHONDONTWRITEBYTECODE=1` deliberately prevents
workers from writing caches. Without build-time compilation, each supervisor
process recompiles the same Python sources during startup.

`scripts/verify-image-bytecode.py --prove-negative-control` runs real Django
startup with an audit hook. The built image must perform no application or
dependency source compilation; a fresh cache path must trigger the detector.
This contract runs inside the Docker build on each architecture. Diagnose slow
startup at this layer before changing startup-probe budgets or resource limits.

Check logs:
```bash
docker compose logs shizuha-notes
```

### Database connection issues

Ensure the database is running and healthy:
```bash
docker compose ps shizuha-db
docker compose logs shizuha-db
```

### Frontend not loading

Check if the backend API is accessible:
```bash
curl http://localhost:8002/shizuha-notes/api/
```

### Search not working

Rebuild the search index:
```bash
docker compose exec shizuha-notes python manage.py rebuild_search_index
```
