# CLAUDE.md - Shizuha Notes

## Overview

**Shizuha Notes** is a personal note-taking service with a rich TipTap editor.

| Setting | Value |
|---------|-------|
| Backend Port | 8012 |
| Frontend Port | 5175 |
| Database | shizuha_notes |
| Redis DB | 3 |
| URL Path | `/notes/` |

## Access

| URL | Description |
|-----|-------------|
| `/notes/` | Notes UI |
| `/notes/api/` | REST API |
| `/notes/admin/` | Django Admin |

## API Endpoints

### Notes
```
GET/POST   /notes/api/notes/               # List/create notes
GET/PATCH  /notes/api/notes/{id}/          # Note details
DELETE     /notes/api/notes/{id}/          # Delete note
```

### Folders
```
GET/POST   /notes/api/folders/             # List/create folders
GET/PATCH  /notes/api/folders/{id}/        # Folder details
GET        /notes/api/folders/{id}/notes/  # Notes in folder
```

### Tags
```
GET/POST   /notes/api/tags/                # List/create tags
GET        /notes/api/notes/?tags=tag1,tag2 # Filter by tags
```

### Search
```
GET /notes/api/search/?q=<query>           # Full-text search
```

## Key Models

- **Note** - Personal note with TipTap JSON content
- **Folder** - Hierarchical organization
- **Tag** - Note categorization
- **NoteVersion** - Version history (auto-saved)

## Features

- Rich text editing with TipTap (ProseMirror-based)
- Folder hierarchy and tag organization
- Full-text search
- Auto-save and version history
- Personal notes (not shared)

## Commands

All development commands run from the `compose/` directory using the master docker-compose.yaml:

```bash
# Start service with frontend
cd compose && docker compose up -d shizuha-notes shizuha-notes-frontend

# Run migrations
cd compose && docker compose exec shizuha-notes python manage.py migrate

# Run tests
cd compose && docker compose exec shizuha-notes python manage.py test

# View logs
cd compose && docker compose logs -f shizuha-notes

```

## Project Structure

```
shizuha-notes/
├── notesmanager/         # Django project settings
├── notes/                # Main app
│   ├── models.py         # Note, Folder, Tag
│   ├── views.py          # DRF ViewSets
│   └── serializers.py    # DRF serializers
└── frontend/             # React UI with TipTap editor
```

Also reference [../CLAUDE.md](../CLAUDE.md) for platform-wide rules.
