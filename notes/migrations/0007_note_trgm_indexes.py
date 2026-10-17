"""
NTS-20: pg_trgm extension + GIN trigram indexes for title fuzzy search and
tag autocomplete. Must run non-atomically (CONCURRENTLY is not allowed inside
a transaction).
"""
from django.db import migrations

_ENABLE_TRGM = "CREATE EXTENSION IF NOT EXISTS pg_trgm;"

_TITLE_TRGM_IDX = (
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS notes_note_title_trgm_idx "
    "ON notes_note USING gin (title gin_trgm_ops);"
)
_TAG_NAME_TRGM_IDX = (
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS notes_tag_name_trgm_idx "
    "ON notes_tag USING gin (lower(name) gin_trgm_ops);"
)

_DROP_TITLE_TRGM_IDX = "DROP INDEX IF EXISTS notes_note_title_trgm_idx;"
_DROP_TAG_NAME_TRGM_IDX = "DROP INDEX IF EXISTS notes_tag_name_trgm_idx;"


class Migration(migrations.Migration):
    atomic = False  # CONCURRENTLY cannot run inside a transaction

    dependencies = [
        ("notes", "0006_note_search_vector_trigger"),
    ]

    operations = [
        migrations.RunSQL(sql=_ENABLE_TRGM, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(sql=_TITLE_TRGM_IDX, reverse_sql=_DROP_TITLE_TRGM_IDX),
        migrations.RunSQL(sql=_TAG_NAME_TRGM_IDX, reverse_sql=_DROP_TAG_NAME_TRGM_IDX),
    ]
