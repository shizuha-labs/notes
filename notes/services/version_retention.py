"""
NoteVersion retention + pruning (NTS-7 / NTS-2 P2).

Bounds per-note version-history growth without losing recent/restorable
history. Safety properties:

- The newest ``keep`` versions are always retained, so the current/head
  version (highest ``version_number``) is never pruned.
- Callers may additionally protect specific version numbers (e.g. the version
  being restored in the same request).
- Pruning is idempotent: re-running it once a note is at/under the cap deletes
  nothing.
- ``safe_prune_note_versions`` never raises — a pruning failure must not roll
  back or fail the user's save. Wire it via ``transaction.on_commit`` so it runs
  only after the save has durably committed.
- Logs carry safe counts/ids only — never note title or content.
"""
import logging

from django.conf import settings

from ..models import NoteVersion

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_CAP = 50


def _retention_cap(keep=None) -> int:
    if keep is None:
        keep = getattr(settings, 'NOTES_VERSION_RETENTION_CAP', DEFAULT_RETENTION_CAP)
    try:
        keep = int(keep)
    except (TypeError, ValueError):
        keep = DEFAULT_RETENTION_CAP
    # A non-positive cap would prune everything including the head; clamp to >=1.
    return max(1, keep)


def prune_note_versions(note_id, *, keep=None, protect=()) -> int:
    """Delete versions of ``note_id`` beyond the retention cap.

    Retains the newest ``keep`` versions (head always included) plus any
    ``protect`` version numbers. Returns the number of versions deleted.
    Raises on DB errors — use ``safe_prune_note_versions`` from request paths.
    """
    keep = _retention_cap(keep)

    # Newest `keep` version ids (ordered by version_number desc → head included).
    keep_ids = set(
        NoteVersion.objects.filter(note_id=note_id)
        .order_by('-version_number')
        .values_list('id', flat=True)[:keep]
    )

    protected_ids = set()
    protect_numbers = [n for n in protect if n is not None]
    if protect_numbers:
        protected_ids = set(
            NoteVersion.objects.filter(
                note_id=note_id, version_number__in=protect_numbers
            ).values_list('id', flat=True)
        )

    retained = keep_ids | protected_ids
    delete_qs = NoteVersion.objects.filter(note_id=note_id).exclude(id__in=retained)
    deleted, _ = delete_qs.delete()
    if deleted:
        logger.info(
            'Pruned %d old note version(s) for note %s (retention cap=%d)',
            deleted, note_id, keep,
        )
    return deleted


def safe_prune_note_versions(note_id, *, keep=None, protect=()) -> int:
    """Best-effort prune that never propagates an error.

    A pruning failure must not fail or roll back the user's save, so this
    swallows and logs any exception and returns 0.
    """
    try:
        return prune_note_versions(note_id, keep=keep, protect=protect)
    except Exception:  # noqa: BLE001 — pruning must never break the save path
        logger.exception('Note version pruning failed for note %s (save unaffected)', note_id)
        return 0
