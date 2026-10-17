# Shizuha Notes API Reference

## Authentication

All API endpoints require JWT authentication via Shizuha ID.

Include the JWT token in the Authorization header:
```
Authorization: Bearer <jwt_token>
```

## Base URL

```
/shizuha-notes/api/
```

## Endpoints

### Notes

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/notes/` | GET | List all notes (paginated) |
| `/api/notes/` | POST | Create a new note |
| `/api/notes/{id}/` | GET | Retrieve a note |
| `/api/notes/{id}/` | PATCH | Update a note (requires `expected_version`) |
| `/api/notes/{id}/` | DELETE | Delete a note |
| `/api/notes/{id}/versions/` | GET | List note versions |
| `/api/notes/{id}/restore_version/` | POST | Restore a version |
| `/api/notes/{id}/trash/` | POST | Move note to trash |
| `/api/notes/{id}/restore/` | POST | Restore from trash |
| `/api/notes/{id}/pin/` | POST | Toggle pin status |
| `/api/notes/{id}/favorite/` | POST | Toggle favorite status |
| `/api/notes/{id}/duplicate/` | POST | Duplicate the note |
| `/api/notes/{id}/share/` | POST | Share the note |
| `/api/notes/{id}/comments/` | GET | List comments |
| `/api/notes/{id}/comments/` | POST | Add comment |

#### Query Parameters (GET /api/notes/)

| Parameter | Type | Description |
|-----------|------|-------------|
| `notebook` | UUID | Filter by notebook |
| `tag` | UUID | Filter by tag |
| `status` | string | Filter by status (draft, published, archived, trashed) |
| `is_pinned` | boolean | Filter pinned notes |
| `is_favorite` | boolean | Filter favorite notes |
| `search` | string | Full-text search |
| `ordering` | string | Sort by field (-updated_at, title, created_at) |

#### Note Object

```json
{
  "id": "uuid",
  "workspace": "uuid",
  "notebook": "uuid",
  "notebook_name": "string",
  "tags": ["uuid"],
  "tag_details": [{"id": "uuid", "name": "string", "color": "string"}],
  "title": "string",
  "version": 1,
  "content_json": {},
  "content_text": "string",
  "status": "draft|published|archived|trashed",
  "is_pinned": false,
  "is_favorite": false,
  "word_count": 0,
  "created_by_id": 1,
  "created_at": "2026-01-30T00:00:00Z",
  "updated_at": "2026-01-30T00:00:00Z"
}
```


#### Optimistic concurrency (PATCH /api/notes/{id}/)

Note reads return a monotonic `version` token. Every PATCH must include the
version the caller read, either as JSON `expected_version` (preferred) or an
`If-Match` header. If another client saved first, the API returns `409` with
`error=version_conflict`, `current_version`, and no content/version-history write
is performed. Caller guidance: re-read the note, re-apply the intended edit onto
the latest content, then retry with the new version.

```json
{
  "title": "Updated title",
  "content_text": "Updated content",
  "expected_version": 3
}
```

### Notebooks

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/notebooks/` | GET | List notebooks |
| `/api/notebooks/` | POST | Create notebook |
| `/api/notebooks/{id}/` | GET | Get notebook |
| `/api/notebooks/{id}/` | PATCH | Update notebook |
| `/api/notebooks/{id}/` | DELETE | Delete notebook |
| `/api/notebooks/{id}/notes/` | GET | List notes in notebook |
| `/api/notebooks/{id}/archive/` | POST | Archive notebook |

#### Notebook Object

```json
{
  "id": "uuid",
  "workspace": "uuid",
  "parent": "uuid|null",
  "name": "string",
  "description": "string",
  "color": "#6366f1",
  "icon": "string",
  "position": 0,
  "is_default": false,
  "is_archived": false,
  "notes_count": 0,
  "created_at": "2026-01-30T00:00:00Z"
}
```

### Tags

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tags/` | GET | List tags |
| `/api/tags/` | POST | Create tag |
| `/api/tags/{id}/` | GET | Get tag |
| `/api/tags/{id}/` | PATCH | Update tag |
| `/api/tags/{id}/` | DELETE | Delete tag |

#### Tag Object

```json
{
  "id": "uuid",
  "workspace": "uuid",
  "name": "string",
  "color": "#6366f1",
  "notes_count": 0
}
```

### Workspaces

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/workspaces/` | GET | List workspaces |
| `/api/workspaces/` | POST | Create workspace |
| `/api/workspaces/{id}/` | GET | Get workspace |
| `/api/workspaces/{id}/` | PATCH | Update workspace |
| `/api/workspaces/{id}/members/` | GET | List members |
| `/api/workspaces/{id}/add_member/` | POST | Add member |
| `/api/workspaces/{id}/remove_member/` | POST | Remove member |

### Search

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/search/` | GET | Full-text search |

#### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `q` | string | Search query (required) |
| `notebook` | UUID | Filter by notebook |
| `tag` | UUID | Filter by tag |

### Trash

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/trash/` | GET | List trashed notes |
| `/api/trash/empty/` | DELETE | Empty trash |

### Attachments

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/attachments/` | POST | Upload attachment |
| `/api/attachments/{id}/` | DELETE | Delete attachment |

## Error Responses

```json
{
  "detail": "Error message"
}
```

| Status Code | Description |
|-------------|-------------|
| 400 | Bad Request |
| 401 | Authentication required |
| 403 | Permission denied |
| 404 | Not found |
| 500 | Server error |
