"""NTS-15 (NTS-11 Slice 4): share-lookup composite indexes.

The pg_trgm extension and the title/tag trigram GIN indexes were delivered by
0007_note_trgm_indexes (NTS-20). This migration adds only the remaining NTS-15
piece: composite indexes for the `shared_with_me` filter hot path on
notes_note_share, scoped to active (non-revoked) shares.

CREATE INDEX CONCURRENTLY (non-blocking) → atomic = False. All statements are
idempotent (IF [NOT] EXISTS) so apply / reverse / retry are safe.
"""
from django.db import migrations


_INDEX_SQL = [
    # shared_with_me by user id, scoped to active shares.
    (
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS notes_note_share_user_revoked_idx "
        "ON notes_note_share (shared_with_user_id, revoked_at);",
        "DROP INDEX CONCURRENTLY IF EXISTS notes_note_share_user_revoked_idx;",
    ),
    # shared_with_me by case-insensitive invite email, scoped to active shares.
    (
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS notes_note_share_email_lower_revoked_idx "
        "ON notes_note_share (lower(shared_with_email), revoked_at);",
        "DROP INDEX CONCURRENTLY IF EXISTS notes_note_share_email_lower_revoked_idx;",
    ),
]


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction block.
    atomic = False

    dependencies = [
        ("notes", "0007_note_trgm_indexes"),
    ]

    operations = [
        migrations.RunSQL(sql=create, reverse_sql=drop)
        for create, drop in _INDEX_SQL
    ]
