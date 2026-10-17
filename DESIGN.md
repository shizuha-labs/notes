# DESIGN.md - Shizuha Notes

Current architecture and implementation of the Notes service.

## Tech Stack

- **Backend**: Django 4.x + Django REST Framework + PostgreSQL + Redis + Celery
- **Frontend**: React 18 + Vite 5 + TanStack Query + Tailwind CSS + TipTap
- **Authentication**: Federated JWT via Shizuha ID

## Project Structure

```
shizuha-notes/
├── notesmanager/          # Django project settings
├── notes/                 # Main Django app
│   ├── models.py          # Workspace, Notebook, Note, Tag, Attachment
│   ├── views.py           # ViewSets and API views
│   ├── serializers.py     # DRF serializers
│   ├── authentication.py  # FederatedUser pattern
│   ├── permissions.py     # Access control
│   └── services/          # Business logic
├── frontend/              # React Vite app
│   └── src/
│       ├── components/    # RichTextEditor, NoteCard, etc.
│       ├── pages/         # Dashboard, Notes, Notebooks, Search
│       └── contexts/      # AuthContext, WorkspaceContext
├── Dockerfile
├── docker-compose.yml     # Standalone compose (also in main stack)
└── requirements.txt
```

## Data Models

- **Workspace**: Personal or organization workspace (multi-tenant)
- **Notebook**: Container for notes (hierarchical)
- **Tag**: Cross-notebook categorization
- **Note**: Core note with TipTap JSON content
- **NoteVersion**: Auto-saved version history
- **Attachment**: File attachments
- **NoteShare**: Sharing configuration

## API Endpoints

| Endpoint | Methods | Description |
|----------|---------|-------------|
| `/api/notes/` | GET, POST | List/create notes |
| `/api/notes/{id}/` | GET, PATCH, DELETE | Note CRUD |
| `/api/notes/{id}/versions/` | GET | Version history |
| `/api/notes/{id}/trash/` | POST | Move to trash |
| `/api/notebooks/` | GET, POST | List/create notebooks |
| `/api/tags/` | GET, POST | List/create tags |
| `/api/search/` | GET | Full-text search |
| `/api/workspaces/` | GET, POST | Workspace management |
| `/api/trash/` | GET, DELETE | Trash operations |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | `True` | Django debug mode |
| `JWT_SECRET_KEY` | - | Shared JWT secret with Shizuha ID |
| `POSTGRES_DB` | `shizuha_notes` | Database name |
| `POSTGRES_HOST` | `shizuha-db` | PostgreSQL host |
| `CELERY_BROKER_URL` | `redis://redis:6379/4` | Celery broker |
| `SHIZUHA_ID_API_URL` | `http://shizuha-id:8001/api` | Shizuha ID service |
| `MAX_ATTACHMENT_SIZE` | `52428800` | Max upload size (50MB) |

## Platform Integration

- Uses Shizuha ID for authentication (JWT tokens)
- FederatedUser pattern creates local user records on-demand
- Shares the same user identity across all Shizuha apps
