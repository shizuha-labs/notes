# Shizuha Notes Documentation

## Overview

Shizuha Notes is a personal note-taking service similar to Evernote, part of the Shizuha Platform.

## Features

- **Rich Text Editor**: TipTap-based editor with formatting, lists, code blocks, and more
- **Notebooks**: Hierarchical organization with colors and icons
- **Tags**: Cross-notebook categorization
- **Full-Text Search**: PostgreSQL FTS for fast searching
- **Version History**: Auto-save with version restore
- **Attachments**: Image and file uploads
- **Sharing**: Share notes via links or with specific users
- **Trash**: Soft delete with 30-day auto-cleanup

## Architecture

```
                    ┌─────────────────┐
                    │   Shizuha ID    │
                    │  (Auth Service) │
                    └────────┬────────┘
                             │ JWT Token
                             ▼
┌──────────────────────────────────────────────────┐
│                  Shizuha Notes                    │
│  ┌──────────────┐  ┌──────────────┐              │
│  │   Frontend   │  │   Backend    │              │
│  │  React/Vite  │  │   Django     │              │
│  │   TipTap     │  │     DRF      │              │
│  └──────────────┘  └──────────────┘              │
│                           │                       │
│                    ┌──────┴──────┐               │
│                    ▼             ▼               │
│              ┌─────────┐  ┌───────────┐          │
│              │PostgreSQL│  │   Redis   │          │
│              │  + FTS   │  │  (Celery) │          │
│              └─────────┘  └───────────┘          │
└──────────────────────────────────────────────────┘
```

## Quick Start

```bash
# Start the service
docker compose up shizuha-notes shizuha-notes-frontend

# Run migrations
docker compose exec shizuha-notes python manage.py migrate

# Access
# Frontend: http://localhost:8002/notes/
# API Docs: http://localhost:8002/shizuha-notes/api/docs/
```

## API Reference

See [API.md](./API.md) for full API documentation.

## Development

See [DEVELOPMENT.md](./DEVELOPMENT.md) for development setup.
