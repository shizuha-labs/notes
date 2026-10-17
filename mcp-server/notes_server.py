#!/usr/bin/env python3
"""
Shizuha Notes MCP Server.

Personal notes tools for AI agents.

Tools (32 total):
- notes_list_notebooks: List notebooks
- notes_create_notebook: Create a notebook
- notes_get_notebook: Get notebook details
- notes_update_notebook: Update a notebook
- notes_delete_notebook: Delete a notebook
- notes_get_notebook_notes: List notes in a notebook
- notes_archive_notebook: Archive a notebook
- notes_unarchive_notebook: Unarchive a notebook
- notes_get_notebook_tree: Get full notebook tree
- notes_move_notebook: Move notebook under another parent
- notes_list_tags: List tags
- notes_create_tag: Create a tag
- notes_get_tag: Get tag details
- notes_update_tag: Update a tag
- notes_delete_tag: Delete a tag
- notes_get_tag_notes: List notes with a specific tag
- notes_list_notes: List notes with filtering
- notes_create_note: Create a new note
- notes_get_note: Get note with full content
- notes_update_note: Update a note
- notes_delete_note: Permanently delete a note
- notes_list_note_versions: List note version history
- notes_restore_note_version: Restore a specific version
- notes_trash_note: Move note to trash
- notes_restore_note: Restore note from trash
- notes_toggle_pin: Toggle pin status
- notes_toggle_favorite: Toggle favorite status
- notes_duplicate_note: Duplicate a note
- notes_list_note_shares: List shares for a note
- notes_share_note: Share a note
- notes_list_note_comments: List comments on a note
- notes_add_note_comment: Add comment to a note
- notes_search_notes: Search and filter notes (full-text + all NTS-11 filter/sort params)
- notes_list_trash: List trashed notes
- notes_empty_trash: Permanently delete all trashed notes
- notes_list_shared: List notes shared with me
- notes_bulk_delete: Bulk delete notes
- notes_bulk_move: Bulk move notes to a notebook
- notes_bulk_tag: Bulk add tags to notes
"""

import argparse
import json
import os
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base import ShizuhaMCPBase, run_mcp_server


def parse_args():
    """Parse command-line arguments for CLI argument compatibility."""
    parser = argparse.ArgumentParser(description="Shizuha Notes MCP Server")
    parser.add_argument(
        "--jwt-token",
        help="JWT token for authentication (overrides SHIZUHA_NOTES_JWT_TOKEN env var)",
    )
    parser.add_argument(
        "--api-url",
        help="Notes API URL (overrides SHIZUHA_NOTES_URL env var)",
    )
    args, _ = parser.parse_known_args()
    return args


# Parse CLI args (for callers that don't pass env vars to MCP subprocesses)
_args = parse_args()

# Configuration priority: CLI args > environment > defaults
NOTES_API_URL = (
    _args.api_url
    or os.environ.get("SHIZUHA_NOTES_URL")
    or os.environ.get("NOTES_API_URL")
)
NOTES_JWT_TOKEN = (
    _args.jwt_token
    or os.environ.get("SHIZUHA_NOTES_JWT_TOKEN")
    or os.environ.get("NOTES_JWT_TOKEN")
    or ""
)

mcp = FastMCP("shizuha-notes", stateless_http=True)

# Advertise OAuth 2.0 discovery metadata so MCP clients can discover the auth server.
from base import _register_oauth_discovery_routes as _reg_oauth_routes
_reg_oauth_routes(mcp, "notes")
base = ShizuhaMCPBase("notes", 8012, api_url=NOTES_API_URL, jwt_token=NOTES_JWT_TOKEN)


# ---------------------------------------------------------------------------
# Notebooks
# ---------------------------------------------------------------------------

@mcp.tool(name="notes_list_notebooks")
def list_notebooks(parent_id: Optional[str] = None) -> str:
    """
    List notebooks.

    Args:
        parent_id: Filter by parent notebook (for nested structure)
    """
    params = {}
    if parent_id:
        params["parent"] = parent_id

    result = base.api_request("GET", "/notebooks/", params=params)
    if "error" in result:
        return base.format_error(result)

    notebooks = (result if isinstance(result, list) else result.get("results", []))
    if not notebooks:
        return "No notebooks found."

    output = f"# Notebooks ({len(notebooks)})\n\n"
    for nb in notebooks:
        status = ""
        if nb.get('is_archived'):
            status = " [archived]"
        output += f"- **{nb.get('name')}**{status}\n"
        output += f"  ID: {nb.get('id')}\n"
        if nb.get('note_count') is not None:
            output += f"  Notes: {nb['note_count']}\n"
        if nb.get('parent_name'):
            output += f"  Parent: {nb['parent_name']}\n"

    return output


@mcp.tool(name="notes_create_notebook")
def create_notebook(
    name: str,
    parent_id: Optional[str] = None,
    description: Optional[str] = None,
    color: Optional[str] = None,
) -> str:
    """
    Create a new notebook.

    Args:
        name: Notebook name
        parent_id: Parent notebook ID (for nesting)
        description: Notebook description
        color: Notebook color (hex code, e.g. '#FF5733')
    """
    data = {"name": name}
    if parent_id:
        data["parent"] = parent_id
    if description:
        data["description"] = description
    if color:
        data["color"] = color

    result = base.api_request("POST", "/notebooks/", data=data)
    if "error" in result:
        return base.format_error(result)

    nb = result
    return (
        f"Notebook created!\n\n"
        f"**Name**: {nb.get('name')}\n"
        f"**ID**: {nb.get('id')}\n"
    )


@mcp.tool(name="notes_get_notebook")
def get_notebook(notebook_id: str) -> str:
    """
    Get notebook details.

    Args:
        notebook_id: Notebook ID (UUID)
    """
    result = base.api_request("GET", f"/notebooks/{notebook_id}/")
    if "error" in result:
        return base.format_error(result)

    nb = result
    output = f"# {nb.get('name')}\n\n"
    output += f"**ID**: {nb.get('id')}\n"
    if nb.get('parent_name'):
        output += f"**Parent**: {nb['parent_name']}\n"
    if nb.get('description'):
        output += f"**Description**: {nb['description']}\n"
    if nb.get('color'):
        output += f"**Color**: {nb['color']}\n"
    output += f"**Notes**: {nb.get('note_count', 0)}\n"
    output += f"**Archived**: {nb.get('is_archived', False)}\n"
    output += f"**Created**: {nb.get('created_at')}\n"
    output += f"**Updated**: {nb.get('updated_at')}\n"

    return output


@mcp.tool(name="notes_update_notebook")
def update_notebook(
    notebook_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    color: Optional[str] = None,
) -> str:
    """
    Update a notebook.

    Args:
        notebook_id: Notebook ID (UUID)
        name: New name
        description: New description
        color: New color (hex code)
    """
    data = {}
    if name:
        data["name"] = name
    if description is not None:
        data["description"] = description
    if color:
        data["color"] = color

    if not data:
        return "Error: No fields provided to update."

    result = base.api_request("PATCH", f"/notebooks/{notebook_id}/", data=data)
    if "error" in result:
        return base.format_error(result)

    nb = result
    return (
        f"Notebook updated!\n\n"
        f"**Name**: {nb.get('name')}\n"
        f"**ID**: {nb.get('id')}\n"
    )


@mcp.tool(name="notes_delete_notebook")
def delete_notebook(notebook_id: str) -> str:
    """
    Delete a notebook. Notes inside may be moved to trash or reassigned.

    Args:
        notebook_id: Notebook ID (UUID)
    """
    result = base.api_request("DELETE", f"/notebooks/{notebook_id}/")
    if "error" in result:
        return base.format_error(result)

    return "Notebook deleted."


@mcp.tool(name="notes_get_notebook_notes")
def get_notebook_notes(notebook_id: str, limit: int = 20) -> str:
    """
    List all notes in a specific notebook.

    Args:
        notebook_id: Notebook ID (UUID)
        limit: Maximum notes to return
    """
    result = base.api_request("GET", f"/notebooks/{notebook_id}/notes/", params={"page_size": limit})
    if "error" in result:
        return base.format_error(result)

    notes = (result if isinstance(result, list) else result.get("results", []))
    if not notes:
        return "No notes found in this notebook."

    output = f"# Notes in Notebook ({len(notes)})\n\n"
    for note in notes:
        icons = ""
        if note.get('is_pinned'):
            icons += "[pinned] "
        if note.get('is_favorite'):
            icons += "[fav] "
        output += f"- {icons}**{note.get('title', 'Untitled')}**\n"
        output += f"  ID: {note.get('id')}\n"
        output += f"  Status: {note.get('status')}\n"
        output += f"  Updated: {note.get('updated_at')}\n"

    return output


@mcp.tool(name="notes_archive_notebook")
def archive_notebook(notebook_id: str) -> str:
    """
    Archive a notebook. Archived notebooks are hidden from default listings.

    Args:
        notebook_id: Notebook ID (UUID)
    """
    result = base.api_request("POST", f"/notebooks/{notebook_id}/archive/")
    if "error" in result:
        return base.format_error(result)

    return "Notebook archived."


@mcp.tool(name="notes_unarchive_notebook")
def unarchive_notebook(notebook_id: str) -> str:
    """
    Unarchive a notebook, making it visible in default listings again.

    Args:
        notebook_id: Notebook ID (UUID)
    """
    result = base.api_request("POST", f"/notebooks/{notebook_id}/unarchive/")
    if "error" in result:
        return base.format_error(result)

    return "Notebook unarchived."


@mcp.tool(name="notes_get_notebook_tree")
def get_notebook_tree() -> str:
    """
    Get the full notebook tree (hierarchical structure).
    """
    result = base.api_request("GET", "/notebooks/tree/")
    if "error" in result:
        return base.format_error(result)

    tree = (result if isinstance(result, list) else result.get("results", []))
    if not tree:
        return "No notebooks found."

    output = "# Notebook Tree\n\n"

    def format_node(node, indent=0):
        prefix = "  " * indent
        archived = " [archived]" if node.get('is_archived') else ""
        out = f"{prefix}- **{node.get('name')}**{archived}\n"
        out += f"{prefix}  ID: {node.get('id')}\n"
        for child in node.get('children', []):
            out += format_node(child, indent + 1)
        return out

    for node in tree:
        output += format_node(node)

    return output


@mcp.tool(name="notes_move_notebook")
def move_notebook(notebook_id: str, parent_id: Optional[str] = None) -> str:
    """
    Move a notebook under a different parent notebook.

    Args:
        notebook_id: Notebook ID to move
        parent_id: New parent notebook ID (None to move to root level)
    """
    data = {"parent": parent_id}

    result = base.api_request("POST", f"/notebooks/{notebook_id}/move/", data=data)
    if "error" in result:
        return base.format_error(result)

    return "Notebook moved successfully."


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

@mcp.tool(name="notes_list_tags")
def list_tags() -> str:
    """
    List all tags.
    """
    result = base.api_request("GET", "/tags/")
    if "error" in result:
        return base.format_error(result)

    tags = (result if isinstance(result, list) else result.get("results", []))
    if not tags:
        return "No tags found."

    output = f"# Tags ({len(tags)})\n\n"
    for tag in tags:
        output += f"- **{tag.get('name')}**\n"
        output += f"  ID: {tag.get('id')}\n"
        if tag.get('color'):
            output += f"  Color: {tag['color']}\n"
        if tag.get('note_count') is not None:
            output += f"  Notes: {tag['note_count']}\n"

    return output


@mcp.tool(name="notes_create_tag")
def create_tag(
    name: str,
    color: Optional[str] = None,
) -> str:
    """
    Create a new tag.

    Args:
        name: Tag name
        color: Tag color (hex code, e.g. '#3B82F6')
    """
    data = {"name": name}
    if color:
        data["color"] = color

    result = base.api_request("POST", "/tags/", data=data)
    if "error" in result:
        return base.format_error(result)

    tag = result
    return (
        f"Tag created!\n\n"
        f"**Name**: {tag.get('name')}\n"
        f"**ID**: {tag.get('id')}\n"
    )


@mcp.tool(name="notes_get_tag")
def get_tag(tag_id: str) -> str:
    """
    Get tag details.

    Args:
        tag_id: Tag ID (UUID)
    """
    result = base.api_request("GET", f"/tags/{tag_id}/")
    if "error" in result:
        return base.format_error(result)

    tag = result
    output = f"# Tag: {tag.get('name')}\n\n"
    output += f"**ID**: {tag.get('id')}\n"
    if tag.get('color'):
        output += f"**Color**: {tag['color']}\n"
    if tag.get('note_count') is not None:
        output += f"**Notes**: {tag['note_count']}\n"
    output += f"**Created**: {tag.get('created_at')}\n"

    return output


@mcp.tool(name="notes_update_tag")
def update_tag(
    tag_id: str,
    name: Optional[str] = None,
    color: Optional[str] = None,
) -> str:
    """
    Update a tag.

    Args:
        tag_id: Tag ID (UUID)
        name: New tag name
        color: New color (hex code)
    """
    data = {}
    if name:
        data["name"] = name
    if color:
        data["color"] = color

    if not data:
        return "Error: No fields provided to update."

    result = base.api_request("PATCH", f"/tags/{tag_id}/", data=data)
    if "error" in result:
        return base.format_error(result)

    tag = result
    return (
        f"Tag updated!\n\n"
        f"**Name**: {tag.get('name')}\n"
        f"**ID**: {tag.get('id')}\n"
    )


@mcp.tool(name="notes_delete_tag")
def delete_tag(tag_id: str) -> str:
    """
    Delete a tag. Notes with this tag will have it removed.

    Args:
        tag_id: Tag ID (UUID)
    """
    result = base.api_request("DELETE", f"/tags/{tag_id}/")
    if "error" in result:
        return base.format_error(result)

    return "Tag deleted."


@mcp.tool(name="notes_get_tag_notes")
def get_tag_notes(tag_id: str, limit: int = 20) -> str:
    """
    List all notes with a specific tag.

    Args:
        tag_id: Tag ID (UUID)
        limit: Maximum notes to return
    """
    result = base.api_request("GET", f"/tags/{tag_id}/notes/", params={"page_size": limit})
    if "error" in result:
        return base.format_error(result)

    notes = (result if isinstance(result, list) else result.get("results", []))
    if not notes:
        return "No notes found with this tag."

    output = f"# Notes with Tag ({len(notes)})\n\n"
    for note in notes:
        output += f"- **{note.get('title', 'Untitled')}**\n"
        output += f"  ID: {note.get('id')}\n"
        output += f"  Status: {note.get('status')}\n"
        output += f"  Updated: {note.get('updated_at')}\n"

    return output


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

@mcp.tool(name="notes_list_notes")
def list_notes(
    notebook_id: Optional[str] = None,
    status: str = "published",
    pinned: Optional[bool] = None,
    favorite: Optional[bool] = None,
    tag: Optional[str] = None,
    limit: int = 20,
) -> str:
    """
    List notes with filtering options.

    Args:
        notebook_id: Filter by notebook
        status: Filter by status (draft, published, archived, trashed)
        pinned: Filter pinned notes only
        favorite: Filter favorite notes only
        tag: Filter by tag name
        limit: Maximum notes to return
    """
    params = {"status": status, "page_size": limit}
    if notebook_id:
        params["notebook"] = notebook_id
    if pinned is not None:
        params["is_pinned"] = pinned
    if favorite is not None:
        params["is_favorite"] = favorite
    if tag:
        params["tag"] = tag

    result = base.api_request("GET", "/notes/", params=params)
    if "error" in result:
        return base.format_error(result)

    notes = (result if isinstance(result, list) else result.get("results", []))
    if not notes:
        return "No notes found."

    output = f"# Notes ({len(notes)})\n\n"
    for note in notes:
        icons = ""
        if note.get('is_pinned'):
            icons += "[pinned] "
        if note.get('is_favorite'):
            icons += "[fav] "
        output += f"- {icons}**{note.get('title', 'Untitled')}**\n"
        output += f"  ID: {note.get('id')}\n"
        output += f"  Status: {note.get('status')}\n"
        output += f"  Version: {note.get('version', 1)}\n"
        if note.get('word_count'):
            output += f"  Words: {note['word_count']} ({note.get('reading_time_minutes', 0)} min read)\n"
        output += f"  Updated: {note.get('updated_at')}\n"

    return output


@mcp.tool(name="notes_create_note")
def create_note(
    title: str,
    content: str,
    notebook_id: Optional[str] = None,
    status: str = "published",
    tags: Optional[str] = None,
) -> str:
    """
    Create a new note.

    Args:
        title: Note title
        content: Note content (plain text or markdown)
        notebook_id: Notebook ID to create note in
        status: Note status (draft, published)
        tags: Comma-separated tag names
    """
    data = {
        "title": title,
        "content_text": content,
        "status": status,
    }
    if notebook_id:
        data["notebook"] = notebook_id
    if tags:
        data["tags"] = [t.strip() for t in tags.split(",")]

    result = base.api_request("POST", "/notes/", data=data)
    if "error" in result:
        return base.format_error(result)

    note = result
    return (
        f"Note created!\n\n"
        f"**Title**: {note.get('title')}\n"
        f"**ID**: {note.get('id')}\n"
        f"**Version**: {note.get('version', 1)}\n"
    )


@mcp.tool(name="notes_get_note")
def get_note(note_id: str) -> str:
    """
    Get a note with full content.

    Args:
        note_id: Note ID (UUID)
    """
    result = base.api_request("GET", f"/notes/{note_id}/")
    if "error" in result:
        return base.format_error(result)

    note = result
    icons = ""
    if note.get('is_pinned'):
        icons += "[pinned] "
    if note.get('is_favorite'):
        icons += "[fav] "

    output = f"# {icons}{note.get('title', 'Untitled')}\n\n"
    output += f"**ID**: {note.get('id')}\n"
    output += f"**Status**: {note.get('status')}\n"
    output += f"**Notebook**: {note.get('notebook_name', note.get('notebook', 'None'))}\n"
    output += f"**Version**: {note.get('version', 1)}\n"

    if note.get('word_count'):
        output += f"**Words**: {note['word_count']} ({note.get('reading_time_minutes', 0)} min read)\n"

    tags = note.get('tags', [])
    if tags:
        tag_names = [t.get('name', str(t)) for t in tags] if isinstance(tags[0], dict) else tags
        output += f"**Tags**: {', '.join(tag_names)}\n"

    output += f"**Created**: {note.get('created_at')}\n"
    output += f"**Updated**: {note.get('updated_at')}\n"

    output += f"\n---\n\n"

    # Content
    if note.get('content_text'):
        output += note['content_text']
    elif note.get('content_html'):
        output += note['content_html']
    elif note.get('content_json'):
        output += f"```json\n{json.dumps(note['content_json'], indent=2)}\n```"
    else:
        output += "(No content)"

    return output


@mcp.tool(name="notes_update_note")
def update_note(
    note_id: str,
    title: Optional[str] = None,
    content: Optional[str] = None,
    status: Optional[str] = None,
    notebook_id: Optional[str] = None,
    tags: Optional[str] = None,
    expected_version: Optional[int] = None,
) -> str:
    """
    Update a note.

    Args:
        note_id: Note ID to update
        title: New title
        content: New content
        status: New status (draft, published, archived)
        notebook_id: Move to different notebook
        tags: Comma-separated tag names (replaces existing tags)
        expected_version: Required NTS-6 optimistic-concurrency token. Pass the
            `version` returned by notes_get_note/notes_list_notes. On 409,
            re-read latest content, re-apply your intended edit, and retry with
            the new version.
    """
    data = {}
    if title:
        data["title"] = title
    if content:
        data["content_text"] = content
    if status:
        data["status"] = status
    if notebook_id:
        data["notebook"] = notebook_id
    if tags is not None:
        data["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    if expected_version is not None:
        data["expected_version"] = expected_version

    if not data or (len(data) == 1 and "expected_version" in data):
        return "Error: No fields provided to update."
    if expected_version is None:
        return (
            "Error: expected_version is required for notes_update_note. "
            "Call notes_get_note first and pass its Version value."
        )

    result = base.api_request("PATCH", f"/notes/{note_id}/", data=data)
    if "error" in result:
        detail = result.get("detail")
        if isinstance(detail, dict) and detail.get("error") == "version_conflict":
            return (
                "⚠️ VERSION CONFLICT — NOT saved (NTS-6 optimistic concurrency).\n"
                f"{detail.get('detail')}\n"
                f"Current version: {detail.get('current_version')}. "
                "Re-read the note, re-apply your intended edit, and retry with expected_version set to the current version."
            )
        return base.format_error(result)

    note = result
    return (
        f"Note updated!\n\n"
        f"**Title**: {note.get('title')}\n"
        f"**Version**: {note.get('version')}\n"
    )


@mcp.tool(name="notes_delete_note")
def delete_note(note_id: str) -> str:
    """
    Permanently delete a note. This cannot be undone.
    Use notes_trash_note to move to trash instead for safe deletion.

    Args:
        note_id: Note ID (UUID)
    """
    result = base.api_request("DELETE", f"/notes/{note_id}/")
    if "error" in result:
        return base.format_error(result)

    return "Note permanently deleted."


@mcp.tool(name="notes_list_note_versions")
def list_note_versions(note_id: str) -> str:
    """
    List version history for a note.

    Args:
        note_id: Note ID (UUID)
    """
    result = base.api_request("GET", f"/notes/{note_id}/versions/")
    if "error" in result:
        return base.format_error(result)

    versions = (result if isinstance(result, list) else result.get("results", []))
    if not versions:
        return "No version history found."

    output = f"# Version History ({len(versions)} versions)\n\n"
    for v in versions:
        output += f"- **Version {v.get('version', v.get('id'))}**\n"
        output += f"  Created: {v.get('created_at')}\n"
        if v.get('changed_by_name') or v.get('changed_by'):
            output += f"  Changed by: {v.get('changed_by_name', v.get('changed_by'))}\n"
        if v.get('title'):
            output += f"  Title: {v['title']}\n"
        if v.get('word_count'):
            output += f"  Words: {v['word_count']}\n"

    return output


@mcp.tool(name="notes_restore_note_version")
def restore_note_version(note_id: str, version: int) -> str:
    """
    Restore a note to a specific version. Creates a new version with the old content.

    Args:
        note_id: Note ID (UUID)
        version: Version number to restore
    """
    result = base.api_request("POST", f"/notes/{note_id}/restore-version/{version}/")
    if "error" in result:
        return base.format_error(result)

    note = result
    return (
        f"Note restored to version {version}!\n\n"
        f"**Current Version**: {note.get('version')}\n"
    )


@mcp.tool(name="notes_trash_note")
def trash_note(note_id: str) -> str:
    """
    Move a note to trash. Can be restored later with notes_restore_note.

    Args:
        note_id: Note ID to trash
    """
    result = base.api_request("POST", f"/notes/{note_id}/trash/")
    if "error" in result:
        return base.format_error(result)

    return "Note moved to trash."


@mcp.tool(name="notes_restore_note")
def restore_note(note_id: str) -> str:
    """
    Restore a note from trash.

    Args:
        note_id: Note ID to restore
    """
    result = base.api_request("POST", f"/notes/{note_id}/restore/")
    if "error" in result:
        return base.format_error(result)

    return "Note restored from trash."


@mcp.tool(name="notes_toggle_pin")
def toggle_pin(note_id: str) -> str:
    """
    Toggle the pinned status of a note. Pinned notes appear at the top of lists.

    Args:
        note_id: Note ID
    """
    result = base.api_request("POST", f"/notes/{note_id}/pin/")
    if "error" in result:
        return base.format_error(result)

    is_pinned = result.get('is_pinned', False)
    return f"Note {'pinned' if is_pinned else 'unpinned'}."


@mcp.tool(name="notes_toggle_favorite")
def toggle_favorite(note_id: str) -> str:
    """
    Toggle the favorite status of a note.

    Args:
        note_id: Note ID
    """
    result = base.api_request("POST", f"/notes/{note_id}/favorite/")
    if "error" in result:
        return base.format_error(result)

    is_favorite = result.get('is_favorite', False)
    return f"Note {'added to' if is_favorite else 'removed from'} favorites."


@mcp.tool(name="notes_duplicate_note")
def duplicate_note(note_id: str, notebook_id: Optional[str] = None) -> str:
    """
    Duplicate a note. Creates a copy with '[Copy]' appended to the title.

    Args:
        note_id: Note ID to duplicate
        notebook_id: Target notebook ID (same notebook if omitted)
    """
    data = {}
    if notebook_id:
        data["notebook"] = notebook_id

    result = base.api_request("POST", f"/notes/{note_id}/duplicate/", data=data)
    if "error" in result:
        return base.format_error(result)

    note = result
    return (
        f"Note duplicated!\n\n"
        f"**New Title**: {note.get('title')}\n"
        f"**New ID**: {note.get('id')}\n"
    )


@mcp.tool(name="notes_list_note_shares")
def list_note_shares(note_id: str) -> str:
    """
    List all shares for a note.

    Args:
        note_id: Note ID (UUID)
    """
    result = base.api_request("GET", f"/notes/{note_id}/shares/")
    if "error" in result:
        return base.format_error(result)

    shares = (result if isinstance(result, list) else result.get("results", []))
    if not shares:
        return "No shares found for this note."

    output = f"# Note Shares ({len(shares)})\n\n"
    for share in shares:
        share_type = share.get('share_type', 'unknown')
        output += f"- **{share_type.title()} Share**\n"
        output += f"  ID: {share.get('id')}\n"
        output += f"  Permission: {share.get('permission')}\n"
        if share.get('shared_with_email'):
            output += f"  Shared with: {share['shared_with_email']}\n"
        if share.get('token'):
            output += f"  Link token: {share['token']}\n"
        if share.get('expires_at'):
            output += f"  Expires: {share['expires_at']}\n"
        output += f"  Created: {share.get('created_at')}\n"

    return output


@mcp.tool(name="notes_share_note")
def share_note(
    note_id: str,
    permission: str = "view",
    email: Optional[str] = None,
    expires_in_days: Optional[int] = None,
) -> str:
    """
    Share a note with others.

    Args:
        note_id: Note ID to share
        permission: Permission level (view, comment, edit)
        email: Share with specific user email (creates user share)
        expires_in_days: Days until share expires (creates public link if no email)
    """
    data = {"permission": permission}
    if email:
        data["shared_with_email"] = email
        data["share_type"] = "user"
    else:
        data["share_type"] = "link"

    if expires_in_days:
        from datetime import datetime, timedelta
        expires_at = datetime.now() + timedelta(days=expires_in_days)
        data["expires_at"] = expires_at.isoformat()

    result = base.api_request("POST", f"/notes/{note_id}/shares/", data=data)
    if "error" in result:
        return base.format_error(result)

    share = result
    output = f"Note shared!\n\n"
    output += f"**Share ID**: {share.get('id')}\n"
    output += f"**Permission**: {share.get('permission')}\n"
    if share.get('token'):
        output += f"**Public Link Token**: {share.get('token')}\n"
    if share.get('shared_with_email'):
        output += f"**Shared With**: {share.get('shared_with_email')}\n"
    if share.get('expires_at'):
        output += f"**Expires**: {share.get('expires_at')}\n"

    return output


@mcp.tool(name="notes_list_note_comments")
def list_note_comments(note_id: str) -> str:
    """
    List all comments on a note.

    Args:
        note_id: Note ID (UUID)
    """
    result = base.api_request("GET", f"/notes/{note_id}/comments/")
    if "error" in result:
        return base.format_error(result)

    comments = (result if isinstance(result, list) else result.get("results", []))
    if not comments:
        return "No comments found."

    output = f"# Comments ({len(comments)})\n\n"
    for c in comments:
        author = c.get('author_name', c.get('author_email', c.get('author', 'Unknown')))
        output += f"**{author}** - {c.get('created_at')}\n"
        output += f"{c.get('content', c.get('text', ''))}\n\n"

    return output


@mcp.tool(name="notes_add_note_comment")
def add_note_comment(note_id: str, content: str) -> str:
    """
    Add a comment to a note.

    Args:
        note_id: Note ID (UUID)
        content: Comment text
    """
    data = {"content": content}

    result = base.api_request("POST", f"/notes/{note_id}/comments/", data=data)
    if "error" in result:
        return base.format_error(result)

    comment = result
    return (
        f"Comment added!\n\n"
        f"**Comment ID**: {comment.get('id')}\n"
    )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _render_snippet(raw: Optional[str]) -> Optional[str]:
    """Convert HTML <mark>…</mark> highlights to **bold** markdown, strip other tags."""
    import re
    if not raw:
        return None
    result = raw.replace('<mark>', '**').replace('</mark>', '**')
    return re.sub(r'<[^>]+>', '', result)


@mcp.tool(name="notes_search_notes")
def search_notes(
    query: str = "",
    limit: int = 20,
    notebook_id: Optional[str] = None,
    tag_ids: Optional[list] = None,
    tag_mode: str = "all",
    favorite: Optional[bool] = None,
    pinned: Optional[bool] = None,
    shared_with_me: bool = False,
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
    updated_after: Optional[str] = None,
    updated_before: Optional[str] = None,
    sort: str = "relevance",
) -> str:
    """
    Search and filter notes. At least one of query or a filter param must be provided.

    Args:
        query:          Full-text search query (title + content). Empty string browses by filter.
        limit:          Maximum results to return (1–50, default 20).
        notebook_id:    Restrict to notes in this notebook UUID.
        tag_ids:        List of tag UUIDs; combined by tag_mode.
        tag_mode:       "all" (AND, default) or "any" (OR) when multiple tag_ids given.
        favorite:       True = favorites only; None = no filter.
        pinned:         True = pinned only; None = no filter.
        shared_with_me: True = notes explicitly shared with the caller only.
        created_after:  ISO 8601 date/datetime lower bound on created_at.
        created_before: ISO 8601 date/datetime upper bound on created_at.
        updated_after:  ISO 8601 date/datetime lower bound on updated_at.
        updated_before: ISO 8601 date/datetime upper bound on updated_at.
        sort:           Sort order — relevance (default), updated_desc, updated_asc,
                        created_desc, created_asc, title_asc, title_desc.
    """
    # Guard: at least one search or filter param must be provided.
    # Without this the REST layer returns 400, which we'd return as an opaque string.
    _filter_args = (notebook_id, tag_ids, favorite, pinned, shared_with_me,
                    created_after, created_before, updated_after, updated_before)
    if not query and not any(_filter_args):
        return "Error: at least one of query or a filter parameter (notebook_id, tag_ids, favorite, pinned, shared_with_me, created_after/before, updated_after/before) must be provided."

    params: dict = {"page_size": min(max(int(limit), 1), 50), "sort": sort}

    if query:
        params["q"] = query
    if notebook_id:
        params["notebook"] = notebook_id
    if tag_ids:
        ids = tag_ids if isinstance(tag_ids, list) else [tag_ids]
        params["tag_ids"] = ",".join(str(t) for t in ids)
        params["tag_mode"] = tag_mode
    if favorite is True:
        params["favorite"] = "true"
    if pinned is True:
        params["pinned"] = "true"
    if shared_with_me:
        params["shared_with_me"] = "true"
    if created_after:
        params["created_after"] = created_after
    if created_before:
        params["created_before"] = created_before
    if updated_after:
        params["updated_after"] = updated_after
    if updated_before:
        params["updated_before"] = updated_before

    result = base.api_request("GET", "/search/", params=params)
    if "error" in result:
        return base.format_error(result)

    notes = result if isinstance(result, list) else result.get("results", [])
    total = result.get("count", len(notes)) if isinstance(result, dict) else len(notes)
    returned_sort = result.get("sort", sort) if isinstance(result, dict) else sort

    if not notes:
        if query:
            return f"No notes found matching '{query}'."
        return "No notes match the given filters."

    label = f"'{query}'" if query else "filters"
    output = f"# Search Results for {label} ({total} total, showing {len(notes)})\n"
    output += f"Sort: {returned_sort}\n\n"

    for note in notes:
        title = note.get('title') or 'Untitled'
        note_id = note.get('id', '')
        output += f"## {title}\n"
        output += f"- **ID**: {note_id}\n"

        notebook = note.get('notebook') or note.get('notebook_id') or note.get('notebook_name')
        if notebook:
            nb_name = notebook.get('name') if isinstance(notebook, dict) else str(notebook)
            output += f"- **Notebook**: {nb_name}\n"

        tags = note.get('tags') or note.get('tag_names') or []
        if tags:
            tag_names = [
                (t.get('name') if isinstance(t, dict) else str(t)) for t in tags
            ]
            output += f"- **Tags**: {', '.join(tag_names)}\n"

        updated = note.get('updated_at', '')
        if updated:
            output += f"- **Updated**: {updated[:10]}\n"

        snippet = _render_snippet(note.get('snippet') or note.get('excerpt'))
        if snippet:
            output += f"- **Snippet**: …{snippet}…\n"

        score = note.get('search_rank') or note.get('score')
        if score:
            try:
                output += f"- **Relevance**: {float(score):.3f}\n"
            except (ValueError, TypeError):
                pass

        output += "\n"

    if isinstance(result, dict):
        total_pages = result.get('total_pages', 1)
        page = result.get('page', 1)
        if total_pages > 1:
            output += f"_Page {page}/{total_pages}. Use `page` param for more._\n"

    return output


@mcp.tool(name="notes_autocomplete_tags")
def autocomplete_tags(query: str, limit: int = 10, notebook_id: str | None = None) -> str:
    """
    Autocomplete tag names for a given prefix — org-scoped.

    Args:
        query: Prefix or partial name (1+ characters)
        limit: Maximum suggestions (default 10, max 25)
        notebook_id: Optional notebook UUID to prioritise tags used in that notebook
    """
    params: dict = {"q": query, "limit": min(limit, 25)}
    if notebook_id:
        params["notebook"] = notebook_id

    result = base.api_request("GET", "/tags/autocomplete/", params=params)
    if "error" in result:
        return base.format_error(result)

    tags = result.get("results", []) if isinstance(result, dict) else result
    if not tags:
        return f"No tags found matching '{query}'."

    output = f"# Tag suggestions for '{query}'\n\n"
    for tag in tags:
        output += f"- **{tag.get('name', '')}** (ID: {tag.get('id')})"
        if tag.get('note_count'):
            output += f" — {tag['note_count']} notes"
        output += "\n"

    return output


# ---------------------------------------------------------------------------
# Trash
# ---------------------------------------------------------------------------

@mcp.tool(name="notes_list_trash")
def list_trash(limit: int = 20) -> str:
    """
    List all notes in the trash.

    Args:
        limit: Maximum notes to return
    """
    result = base.api_request("GET", "/trash/", params={"page_size": limit})
    if "error" in result:
        return base.format_error(result)

    notes = (result if isinstance(result, list) else result.get("results", []))
    if not notes:
        return "Trash is empty."

    output = f"# Trash ({len(notes)} notes)\n\n"
    for note in notes:
        output += f"- **{note.get('title', 'Untitled')}**\n"
        output += f"  ID: {note.get('id')}\n"
        output += f"  Trashed: {note.get('trashed_at', note.get('updated_at'))}\n"

    return output


@mcp.tool(name="notes_empty_trash")
def empty_trash() -> str:
    """
    Permanently delete ALL notes in the trash. This cannot be undone.
    """
    result = base.api_request("DELETE", "/trash/")
    if "error" in result:
        return base.format_error(result)

    return "Trash emptied. All trashed notes have been permanently deleted."


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------

@mcp.tool(name="notes_list_shared")
def list_shared(limit: int = 20) -> str:
    """
    List notes that have been shared with the current user.

    Args:
        limit: Maximum notes to return
    """
    result = base.api_request("GET", "/shared/", params={"page_size": limit})
    if "error" in result:
        return base.format_error(result)

    notes = (result if isinstance(result, list) else result.get("results", []))
    if not notes:
        return "No shared notes found."

    output = f"# Shared With Me ({len(notes)})\n\n"
    for note in notes:
        output += f"- **{note.get('title', 'Untitled')}**\n"
        output += f"  ID: {note.get('id')}\n"
        output += f"  Permission: {note.get('permission', 'view')}\n"
        if note.get('shared_by_name') or note.get('shared_by'):
            output += f"  Shared by: {note.get('shared_by_name', note.get('shared_by'))}\n"

    return output


# ---------------------------------------------------------------------------
# Bulk Operations
# ---------------------------------------------------------------------------

@mcp.tool(name="notes_bulk_delete")
def bulk_delete(note_ids: str) -> str:
    """
    Bulk delete multiple notes (moves them to trash).

    Args:
        note_ids: Comma-separated note IDs
    """
    ids = [nid.strip() for nid in note_ids.split(",") if nid.strip()]
    if not ids:
        return "Error: No note IDs provided."

    data = {"note_ids": ids}

    result = base.api_request("POST", "/notes/bulk-delete/", data=data)
    if "error" in result:
        return base.format_error(result)

    count = result.get('deleted_count', result.get('count', len(ids)))
    return f"Bulk delete complete. {count} notes moved to trash."


@mcp.tool(name="notes_bulk_move")
def bulk_move(note_ids: str, notebook_id: str) -> str:
    """
    Bulk move multiple notes to a notebook.

    Args:
        note_ids: Comma-separated note IDs
        notebook_id: Target notebook ID
    """
    ids = [nid.strip() for nid in note_ids.split(",") if nid.strip()]
    if not ids:
        return "Error: No note IDs provided."

    data = {"note_ids": ids, "notebook": notebook_id}

    result = base.api_request("POST", "/notes/bulk-move/", data=data)
    if "error" in result:
        return base.format_error(result)

    count = result.get('moved_count', result.get('count', len(ids)))
    return f"Bulk move complete. {count} notes moved."


@mcp.tool(name="notes_bulk_tag")
def bulk_tag(note_ids: str, tags: str) -> str:
    """
    Bulk add tags to multiple notes.

    Args:
        note_ids: Comma-separated note IDs
        tags: Comma-separated tag names to add
    """
    ids = [nid.strip() for nid in note_ids.split(",") if nid.strip()]
    if not ids:
        return "Error: No note IDs provided."

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    if not tag_list:
        return "Error: No tags provided."

    data = {"note_ids": ids, "tags": tag_list}

    result = base.api_request("POST", "/notes/bulk-tag/", data=data)
    if "error" in result:
        return base.format_error(result)

    count = result.get('tagged_count', result.get('count', len(ids)))
    return f"Bulk tag complete. Tags added to {count} notes."


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """Run the MCP server."""
    run_mcp_server(mcp, base)


if __name__ == "__main__":
    main()
