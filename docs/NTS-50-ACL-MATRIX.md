# NTS-50 — Notes endpoints / MCP + ACL matrix

**Pulse:** NTS-50 · Parent: **NTS-34** · Remediation sibling: **NTS-51**  
**Exact inventory head:** this branch  
**Rule:** no client-only scoping counts as enforcement.

## Principals

| Principal | Source |
|-----------|--------|
| Authenticated user | JWT / session |
| Org member | `organization_id` / JWT orgs |
| Org admin/owner | JWT `organization_role` ∈ {owner, admin} or superuser |
| Note owner | `can_access` / `build_authorized_queryset` |
| Share grantee (active non-expired) | `NoteShare` + role (view/comment/edit) |
| Link-token holder | `public/<token>/` **requires authentication** (NTS-3/NTS-34: no anonymous) |
| Service-enabled | `enabled_services` contains `notes` |

## Note content ACL (canonical)

**NTS-3 / NTS-34 hard rule for note *content*:** principal may access a note iff **owner ∪ explicit share grant** (org partition on shares). Org membership alone does **not** reveal another user's note content/existence. Entry points: `can_access`, `has_role`, `build_authorized_queryset`.

**NTS-51 owned-object rule:** notebooks and tags use the same principal shape:
**owner ∪ active `OwnedObjectShare` grant ∪ audited admin break-glass**, within
the selected organization. A selected `X-Organization-ID` is an active-workspace
boundary and is never widened to the caller's other memberships. Safe access
accepts view/comment/edit grants; mutation and relation/bulk targets require edit.
Entry points: `authorized_owned_filter` and `can_access_owned`.

## HTTP surface (exhaustive — one row per method+path)

### Notebooks — `NotebookViewSet` (`IsAuthenticated` + canonical owned-object ACL)

| Method | Path | Enforcement | Gap |
|--------|------|-------------|-----|
| GET | `/api/notebooks/` | owner ∪ active share; selected-org | resolved NTS-51 |
| POST | `/api/notebooks/` | stamps owner + selected org | resolved NTS-51 |
| GET | `/api/notebooks/{id}/` | owner ∪ share ∪ audited break-glass | resolved NTS-51 |
| PUT | `/api/notebooks/{id}/` | owner ∪ edit share ∪ audited break-glass | resolved NTS-51 |
| PATCH | `/api/notebooks/{id}/` | owner ∪ edit share ∪ audited break-glass | resolved NTS-51 |
| DELETE | `/api/notebooks/{id}/` | owner ∪ edit share ∪ audited break-glass | resolved NTS-51 |
| GET | `/api/notebooks/{id}/notes/` | authorized notes ∩ notebook | note content OK |
| POST | `/api/notebooks/{id}/archive/` | owner ∪ edit share ∪ audited break-glass | resolved NTS-51 |
| POST | `/api/notebooks/{id}/unarchive/` | owner ∪ edit share ∪ audited break-glass | resolved NTS-51 |
| GET | `/api/notebooks/tree/` | owner ∪ share; ACL-filtered children/counts | resolved NTS-51 |
| POST | `/api/notebooks/{id}/move/` | source + parent require owner/edit share | resolved NTS-51 |

### Tags — `TagViewSet` (`IsAuthenticated` + canonical owned-object ACL)

| Method | Path | Enforcement | Gap |
|--------|------|-------------|-----|
| GET | `/api/tags/` | owner ∪ active share; selected-org | resolved NTS-51 |
| POST | `/api/tags/` | stamps owner + selected org | resolved NTS-51 |
| GET | `/api/tags/{id}/` | owner ∪ share ∪ audited break-glass | resolved NTS-51 |
| PUT | `/api/tags/{id}/` | owner ∪ edit share ∪ audited break-glass | resolved NTS-51 |
| PATCH | `/api/tags/{id}/` | owner ∪ edit share ∪ audited break-glass | resolved NTS-51 |
| DELETE | `/api/tags/{id}/` | owner ∪ edit share ∪ audited break-glass | resolved NTS-51 |
| GET | `/api/tags/{id}/notes/` | authorized notes ∩ tag | note content OK |
| GET | `/api/tags/autocomplete/` | owner ∪ active share; selected-org | resolved NTS-51 |

### Notes — `NoteViewSet` (`IsAuthenticated` + object via `can_access`)

| Method | Path | Enforcement |
|--------|------|-------------|
| GET | `/api/notes/` | `build_authorized_queryset` |
| POST | `/api/notes/` | relation targets require owner/edit share | resolved NTS-51 |
| GET | `/api/notes/{id}/` | owner∪share |
| PUT | `/api/notes/{id}/` | note edit role + relation targets owner/edit share | resolved NTS-51 |
| PATCH | `/api/notes/{id}/` | note edit role + relation targets owner/edit share | resolved NTS-51 |
| DELETE | `/api/notes/{id}/` | edit role |
| GET | `/api/notes/{id}/versions/` | object perm |
| GET | `/api/notes/{id}/versions/{n}/` | object perm |
| POST | `/api/notes/{id}/restore-version/{n}/` | edit |
| POST | `/api/notes/{id}/restore-version/{n}/as-copy/` | edit |
| POST | `/api/notes/{id}/trash/` | edit |
| POST | `/api/notes/{id}/restore/` | authorized + edit |
| POST | `/api/notes/{id}/pin/` | edit |
| POST | `/api/notes/{id}/favorite/` | edit |
| POST | `/api/notes/{id}/duplicate/` | edit |
| GET | `/api/notes/{id}/shares/` | **owner only** (NTS-3) |
| POST | `/api/notes/{id}/shares/` | **owner only** |
| DELETE | `/api/notes/{id}/shares/{share_id}/` | **owner only** |
| GET | `/api/notes/{id}/comments/` | read role |
| POST | `/api/notes/{id}/comments/` | comment role |
| GET | `/api/notes/{id}/drafts/` | note access + draft `user_id` filter |
| POST | `/api/notes/{id}/drafts/` | note **edit** role (`IsNoteOwnerOrOrgMember`) + draft owner |
| GET | `/api/notes/{id}/drafts/{draft_id}/` | note access + draft owner |
| DELETE | `/api/notes/{id}/drafts/{draft_id}/` | note **edit** role + draft owner |
| POST | `/api/notes/{id}/drafts/{draft_id}/copy/` | note **edit** role + draft owner |

### Attachments — `AttachmentViewSet` (ModelViewSet)

| Method | Path | Enforcement |
|--------|------|-------------|
| GET | `/api/attachments/` | QS `note__in=build_authorized_queryset` |
| POST | `/api/attachments/` | `_require_note_role(..., edit)` |
| GET | `/api/attachments/{id}/` | authorized parent note |
| PUT | `/api/attachments/{id}/` | `perform_update` → edit role |
| PATCH | `/api/attachments/{id}/` | `perform_update` → edit role |
| DELETE | `/api/attachments/{id}/` | `perform_destroy` → edit role |
| GET | `/api/attachments/{id}/file/` | authorized QS; 404 if no access |

### Search / trash / shared / public / bulk

| Method | Path | Enforcement |
|--------|------|-------------|
| GET | `/api/search/` | authorized queryset + filters |
| GET | `/api/trash/` | authorized ∩ trashed |
| DELETE | `/api/trash/` | canonical authorized queryset ∩ owner ∩ selected-org; shares never delete | resolved NTS-51 |
| GET | `/api/shared/` | active share join |
| GET | `/api/public/<token>/` | `IsAuthenticated` + `can_access(..., link_token=)` — no anonymous |
| POST | `/api/notes/bulk-delete/` | authorized ids + `has_role(..., edit)` per note |
| POST | `/api/notes/bulk-move/` | source note edit + target notebook owner/edit share | resolved NTS-51 |
| POST | `/api/notes/bulk-tag/` | source note edit + all target tags owner/edit share | resolved NTS-51 |

### Health / auth / media / absent surfaces

| Path | Notes |
|------|-------|
| `GET /api/health/` | public health |
| `/api/auth/*` | OAuth/JWT (out of content ACL) |
| media serve | prod: no unauth route |
| **export / notification APIs** | **not present** in this service surface |

## MCP tools — per-tool principal + HTTP ACL inheritance (exactly 40)

MCP tools call the Notes HTTP API with the caller's user JWT (or agent token). They inherit the same server-side ACL as the mapped HTTP route; MCP does not add a second authorization layer.

| # | MCP tool | HTTP | Principal / current enforcement | Gap |
|---|----------|------|----------------------------------|-----|
| 1 | `notes_list_notebooks` | GET `/api/notebooks/` | owner ∪ active share; selected-org | resolved NTS-51 |
| 2 | `notes_create_notebook` | POST `/api/notebooks/` | stamps owner + selected org | resolved NTS-51 |
| 3 | `notes_get_notebook` | GET `/api/notebooks/{id}/` | owner ∪ share ∪ audited break-glass | resolved NTS-51 |
| 4 | `notes_update_notebook` | PATCH `/api/notebooks/{id}/` | owner ∪ edit share ∪ audited break-glass | resolved NTS-51 |
| 5 | `notes_delete_notebook` | DELETE `/api/notebooks/{id}/` | owner ∪ edit share ∪ audited break-glass | resolved NTS-51 |
| 6 | `notes_get_notebook_notes` | GET `/api/notebooks/{id}/notes/` | owner∪share notes in notebook | OK |
| 7 | `notes_archive_notebook` | POST `/api/notebooks/{id}/archive/` | owner ∪ edit share ∪ audited break-glass | resolved NTS-51 |
| 8 | `notes_unarchive_notebook` | POST `/api/notebooks/{id}/unarchive/` | owner ∪ edit share ∪ audited break-glass | resolved NTS-51 |
| 9 | `notes_get_notebook_tree` | GET `/api/notebooks/tree/` | owner ∪ share, ACL-filtered tree | resolved NTS-51 |
| 10 | `notes_move_notebook` | POST `/api/notebooks/{id}/move/` | source + parent owner/edit share | resolved NTS-51 |
| 11 | `notes_list_tags` | GET `/api/tags/` | owner ∪ active share; selected-org | resolved NTS-51 |
| 12 | `notes_create_tag` | POST `/api/tags/` | stamps owner + selected org | resolved NTS-51 |
| 13 | `notes_get_tag` | GET `/api/tags/{id}/` | owner ∪ share ∪ audited break-glass | resolved NTS-51 |
| 14 | `notes_update_tag` | PATCH `/api/tags/{id}/` | owner ∪ edit share ∪ audited break-glass | resolved NTS-51 |
| 15 | `notes_delete_tag` | DELETE `/api/tags/{id}/` | owner ∪ edit share ∪ audited break-glass | resolved NTS-51 |
| 16 | `notes_get_tag_notes` | GET `/api/tags/{id}/notes/` | owner∪share notes with tag | OK |
| 17 | `notes_list_notes` | GET `/api/notes/` | owner∪share | OK |
| 18 | `notes_create_note` | POST `/api/notes/` | relation targets require owner/edit share | resolved NTS-51 |
| 19 | `notes_get_note` | GET `/api/notes/{id}/` | owner∪share | OK |
| 20 | `notes_update_note` | PATCH `/api/notes/{id}/` | note edit + relation target owner/edit share | resolved NTS-51 |
| 21 | `notes_delete_note` | DELETE `/api/notes/{id}/` | edit role | OK |
| 22 | `notes_list_note_versions` | GET `/api/notes/{id}/versions/` | object perm | OK |
| 23 | `notes_restore_note_version` | POST `/api/notes/{id}/restore-version/{n}/` | edit | OK |
| 24 | `notes_trash_note` | POST `/api/notes/{id}/trash/` | edit | OK |
| 25 | `notes_restore_note` | POST `/api/notes/{id}/restore/` | authorized + edit | OK |
| 26 | `notes_toggle_pin` | POST `/api/notes/{id}/pin/` | edit | OK |
| 27 | `notes_toggle_favorite` | POST `/api/notes/{id}/favorite/` | edit | OK |
| 28 | `notes_duplicate_note` | POST `/api/notes/{id}/duplicate/` | edit | OK |
| 29 | `notes_list_note_shares` | GET `/api/notes/{id}/shares/` | **owner only** | OK |
| 30 | `notes_share_note` | POST `/api/notes/{id}/shares/` | **owner only** | OK |
| 31 | `notes_list_note_comments` | GET `/api/notes/{id}/comments/` | read role | OK |
| 32 | `notes_add_note_comment` | POST `/api/notes/{id}/comments/` | comment role | OK |
| 33 | `notes_search_notes` | GET `/api/search/` | authorized queryset | OK |
| 34 | `notes_autocomplete_tags` | GET `/api/tags/autocomplete/` | owner ∪ active share; selected-org | resolved NTS-51 |
| 35 | `notes_list_trash` | GET `/api/trash/` | authorized ∩ trashed | OK |
| 36 | `notes_empty_trash` | DELETE `/api/trash/` | canonical ACL ∩ owner ∩ selected-org | resolved NTS-51 |
| 37 | `notes_list_shared` | GET `/api/shared/` | active share join | OK |
| 38 | `notes_bulk_delete` | POST `/api/notes/bulk-delete/` | authorized + edit per id | OK (NTS-38) |
| 39 | `notes_bulk_move` | POST `/api/notes/bulk-move/` | source note edit; target notebook owner/edit share | resolved NTS-51 |
| 40 | `notes_bulk_tag` | POST `/api/notes/bulk-tag/` | source note edit; all target tags owner/edit share | resolved NTS-51 |

There is **no** separate `search_notes` MCP export beyond `notes_search_notes`. MCP tools for draft detail/copy, attachment CRUD, share revoke, and public-link open are **not exported** (HTTP still enforces ACL if called directly).

## Gaps (linked siblings)

| ID | Exact current behavior | Sibling |
|----|------------------------|---------|
| **GAP-NB** | Resolved: canonical owner/share/break-glass helper on notebook surfaces and bulk target | **NTS-51** |
| **GAP-TAG** | Resolved: canonical owner/share/break-glass helper on tag surfaces and bulk target | **NTS-51** |
| **GAP-TRASH-ORG** | Resolved: selected-org authorized queryset intersected with owner before delete | **NTS-51** |
| **GAP-REL** | Resolved: serializer relation querysets require owner/edit-share authorization | **NTS-51** |
| Attachments list/serve/create/update/destroy | Server-scoped to authorized notes + edit role on mutate | **NTS-38** + current code |
| Bulk | source notes: per-id authorized + edit; targets: owner/edit share + selected-org | **NTS-38** source; **NTS-51** target |
| Public link | authenticated + token | NTS-3/NTS-34 by design |

Pulse links: parent **NTS-34**; remediation **NTS-51**; attachment/bulk control **NTS-38**.

## Explicit non-acceptance

- Frontend route guards alone ≠ done.  
- MCP omitting a tool ≠ protection if HTTP is open.  
- Placeholders are not inventory.

## Naming debt

`IsNoteOwnerOrOrgMember` is historical: note content is owner∪share, not bare org membership.
