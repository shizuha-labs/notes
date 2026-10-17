"""
Shared search service for Notes — NTS-12.

Provides build_authorized_queryset + apply_filters + apply_sort used by
SearchView, NoteViewSet, and future MCP tools so the security predicate
and filter logic cannot drift between callsites.
"""
from datetime import datetime, timezone as dt_timezone

from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from ..middleware import get_user_organization_ids, set_organization_context
from .access import authorized_note_filter, active_share_filter


MAX_TAG_IDS = 10

SORT_MAP = {
    'updated_desc': ['-updated_at'],
    'updated_asc': ['updated_at'],
    'created_desc': ['-created_at'],
    'created_asc': ['created_at'],
    'title_asc': ['title'],
    'title_desc': ['-title'],
}


def _get_user_id(request):
    """Extract integer user_id from the request user (works for JWT + regular auth)."""
    user = request.user
    uid = getattr(user, 'id', None) or getattr(user, 'pk', None)
    try:
        return int(uid) if uid is not None else None
    except (ValueError, TypeError):
        return uid


def _get_org_filter(request):
    """
    Build the organization membership filter.

    If X-Organization-ID is validated on the request, filter to that org.
    Otherwise include all orgs the user belongs to.
    Returns an empty predicate (no notes visible) when org membership is absent —
    a user evicted from all orgs must not see notes via the creator-fallback path.
    """
    org_id = getattr(request, 'organization_id', None)
    if org_id:
        return Q(organization_id=org_id)
    org_ids = get_user_organization_ids(request)
    if org_ids:
        return Q(organization_id__in=org_ids)
    # No org membership: surface nothing rather than leaking creator-owned notes.
    return Q(pk__in=[])


def build_authorized_queryset(request):
    """
    Return a Note queryset of every note the caller is authorized to see.

    NTS-3 security predicate applied before any ranking/filtering:
        note.created_by_id == caller
        OR EXISTS active non-expired share for caller/link with org boundary.

    Does NOT filter by status — apply_filters() handles the default trashed
    exclusion so callers that explicitly request ?status=trashed can still do so.
    """
    from ..models import Note
    set_organization_context(request)
    return Note.objects.filter(authorized_note_filter(request)).distinct()

def _parse_iso(value):
    """Parse an ISO datetime or date string; returns an aware datetime or None."""
    if not value:
        return None
    for fmt in (
        '%Y-%m-%dT%H:%M:%S.%fZ',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%dT%H:%M:%S.%f',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%d',
    ):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=dt_timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def apply_filters(queryset, params, user_id, *, user_email=None):
    """
    Apply NTS-11 filter parameters to an authorized Note queryset.

    params     — any mapping with .get() (e.g. request.query_params or dict).
    user_id    — integer caller user ID.
    user_email — caller email for share email-fallback lookup.

    Returns the filtered (unsorted) queryset. Call apply_sort() after.
    """
    # -- status (default: exclude trashed)
    status_param = params.get('status')
    if status_param:
        queryset = queryset.filter(status=status_param)
    else:
        queryset = queryset.exclude(status='trashed')

    # -- notebook
    notebook = params.get('notebook')
    if notebook:
        queryset = queryset.filter(notebook_id=notebook)

    # -- tag / tag_ids + tag_mode
    tag_ids = []
    tag_single = params.get('tag')
    if tag_single:
        tag_ids.append(tag_single)
    tag_ids_param = params.get('tag_ids', '')
    if tag_ids_param:
        if isinstance(tag_ids_param, list):
            tag_ids.extend(tag_ids_param)
        else:
            tag_ids.extend(t.strip() for t in tag_ids_param.split(',') if t.strip())

    if tag_ids:
        if len(tag_ids) > MAX_TAG_IDS:
            raise ValidationError(
                f"Too many tag filters: {len(tag_ids)} supplied, maximum is {MAX_TAG_IDS}."
            )
        tag_mode = (params.get('tag_mode') or 'all').lower()
        if tag_mode == 'any':
            queryset = queryset.filter(tags__id__in=tag_ids).distinct()
        else:
            # AND semantics: chain a filter per tag so each must be present.
            # .distinct() prevents row duplication from the multi-JOIN.
            for tid in tag_ids:
                queryset = queryset.filter(tags__id=tid)
            queryset = queryset.distinct()

    # -- favorite / pinned
    fav = params.get('favorite', '')
    if (isinstance(fav, bool) and fav) or str(fav).lower() == 'true':
        queryset = queryset.filter(is_favorite=True)

    pin = params.get('pinned', '')
    if (isinstance(pin, bool) and pin) or str(pin).lower() == 'true':
        queryset = queryset.filter(is_pinned=True)

    # -- shared_with_me: restrict to notes explicitly shared with this caller
    swm = params.get('shared_with_me', '')
    apply_swm = swm if isinstance(swm, bool) else str(swm).lower() == 'true'
    if apply_swm:
        queryset = queryset.filter(
            active_share_filter(user_id, user_email=user_email)
        ).distinct()

    # -- date range filters
    created_after = _parse_iso(params.get('created_after'))
    if created_after:
        queryset = queryset.filter(created_at__gte=created_after)
    created_before = _parse_iso(params.get('created_before'))
    if created_before:
        queryset = queryset.filter(created_at__lt=created_before)
    updated_after = _parse_iso(params.get('updated_after'))
    if updated_after:
        queryset = queryset.filter(updated_at__gte=updated_after)
    updated_before = _parse_iso(params.get('updated_before'))
    if updated_before:
        queryset = queryset.filter(updated_at__lt=updated_before)

    return queryset


def apply_sort(queryset, sort, *, has_query=False):
    """
    Apply sort ordering to a Note queryset.

    sort      — sort enum string or None/empty for default ordering.
    has_query — True when search_rank is annotated (enables 'relevance' ordering).
    """
    if sort == 'relevance':
        if has_query:
            return queryset.order_by('-search_rank', '-updated_at')
        return queryset.order_by('-updated_at')

    ordering = SORT_MAP.get(sort or '')
    if ordering:
        return queryset.order_by(*ordering)

    # Default browse ordering: pinned first, most recently updated
    return queryset.order_by('-is_pinned', '-updated_at')
