from django.db import migrations


_CREATE_FUNC = """
CREATE OR REPLACE FUNCTION notes_note_search_vector_update()
RETURNS trigger AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('pg_catalog.english', coalesce(NEW.title, '')), 'A') ||
    setweight(to_tsvector('pg_catalog.english', coalesce(NEW.content_text, '')), 'B');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_CREATE_TRIGGER = """
CREATE TRIGGER notes_note_search_vector_trigger
  BEFORE INSERT OR UPDATE OF title, content_text
  ON notes_note
  FOR EACH ROW EXECUTE FUNCTION notes_note_search_vector_update();
"""

# Backfill rows that were written before the trigger existed.
_BACKFILL = """
UPDATE notes_note
SET search_vector =
      setweight(to_tsvector('pg_catalog.english', coalesce(title, '')), 'A') ||
      setweight(to_tsvector('pg_catalog.english', coalesce(content_text, '')), 'B');
"""

_DROP_TRIGGER = "DROP TRIGGER IF EXISTS notes_note_search_vector_trigger ON notes_note;"
_DROP_FUNC = "DROP FUNCTION IF EXISTS notes_note_search_vector_update();"


class Migration(migrations.Migration):

    dependencies = [
        ("notes", "0005_note_draft"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[_CREATE_FUNC, _CREATE_TRIGGER, _BACKFILL],
            reverse_sql=[_DROP_TRIGGER, _DROP_FUNC],
        ),
    ]
