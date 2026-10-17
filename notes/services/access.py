"""Canonical Notes authorization predicates for NTS-3/NTS-51.

Every note/notebook/tag path derives owner | explicit share | audited
break-glass decisions from this module instead of re-implementing endpoint ACLs.
"""
from dataclasses import dataclass
from typing import Optional

from django.db.models import OuterRef, Q, Subquery
from django.utils import timezone

from ..middleware import get_user_organization_ids, set_organization_context

ROLE_ORDER = {'view': 1, 'comment': 2, 'edit': 3}


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    role: Optional[str] = None
    share: object = None
    source: Optional[str] = None


def normalize_user_id(user_or_id):
    """Return an int user id where possible; tolerate mock/federated users."""
    if hasattr(user_or_id, 'id') or hasattr(user_or_id, 'pk'):
        value = getattr(user_or_id, 'id', None) or getattr(user_or_id, 'pk', None)
    else:
        value = user_or_id
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return value


def _user_org_ids(request=None):
    if request is None:
        return []
    try:
        return list(get_user_organization_ids(request) or [])
    except Exception:
        return []


def _share_org_allowed(share, request=None):
    """Fail closed when a share is org-scoped and membership is unavailable."""
    org_id = getattr(share, 'organization_id', None)
    if not org_id:
        return True
    request_org_id = (
        getattr(request, 'organization_id', None) if request is not None else None
    )
    if request_org_id:
        return request_org_id == org_id
    return org_id in _user_org_ids(request)


def _active_share_queryset(now=None):
    from ..models import NoteShare
    now = now or timezone.now()
    return NoteShare.objects.filter(
        is_active=True,
        revoked_at__isnull=True,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))


def active_share_filter(user_id, *, user_email=None, request=None, link_token=None, related_prefix='shares__'):
    """Q predicate for active shares matching a caller.

    By default the predicate targets a `Note` queryset through its `shares`
    relation. Pass `related_prefix=''` when filtering `NoteShare` directly.
    """
    def f(name):
        return f"{related_prefix}{name}"

    now = timezone.now()
    target_q = Q(**{f('shared_with_user_id'): user_id})
    if user_email:
        target_q |= Q(**{f('shared_with_email'): user_email})
    if link_token:
        target_q |= Q(**{f('public_link_token'): link_token, f('is_public_link'): True})

    share_q = (
        Q(**{f('is_active'): True}) &
        Q(**{f('revoked_at__isnull'): True}) &
        (Q(**{f('expires_at__isnull'): True}) | Q(**{f('expires_at__gt'): now})) &
        target_q
    )

    request_org_id = (
        getattr(request, 'organization_id', None) if request is not None else None
    )
    allowed_orgs = (
        {request_org_id} if request_org_id else set(_user_org_ids(request))
    )
    if allowed_orgs:
        share_q &= (Q(**{f('organization_id__isnull'): True}) | Q(**{f('organization_id__in'): list(allowed_orgs)}))
    else:
        share_q &= Q(**{f('organization_id__isnull'): True})
    return share_q


def _owned_note_org_filter(request):
    """Org-scope predicate for the owner leg of note visibility.

    NTS-42: a multi-org user may own notes in several organizations, but an
    explicit X-Organization-ID request is an active-workspace boundary. Owner
    visibility therefore needs the same org predicate as notebook/tag/list
    surfaces; otherwise search/list/detail leak the caller's own org-B notes
    into org-A. Explicit shares remain handled by active_share_filter().
    """
    request_org_id = (
        getattr(request, 'organization_id', None) if request is not None else None
    )
    if request_org_id:
        return Q(organization_id=request_org_id)

    org_ids = _user_org_ids(request)
    if org_ids:
        return Q(organization_id__in=org_ids)

    # No validated org membership: fail closed for owner/org-owned visibility.
    return Q(pk__in=[])


def authorized_note_filter(request):
    """Owner ∪ active-share predicate for note querysets (NTS-3 INV-1)."""
    user = request.user
    user_id = normalize_user_id(user)
    user_email = getattr(user, 'email', None)
    owner_q = Q(created_by_id=user_id) & _owned_note_org_filter(request)
    share_q = active_share_filter(user_id, user_email=user_email, request=request)
    return owner_q | share_q


def is_privileged(request):
    """Org admin / owner / superuser — the only principal that may break-glass."""
    user = getattr(request, 'user', None)
    if user is None:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return getattr(user, 'organization_role', None) in ('owner', 'admin')


def record_break_glass(request, *, object_type, obj, event_type='break_glass', decision='allow', metadata=None):
    """Persist a MANDATORY break-glass audit row. Returns True only if it
    committed. Callers MUST fail closed (deny) when this returns False — an
    un-auditable privileged access is not permitted (NTS-51 P1)."""
    from ..models import AccessAudit
    user = getattr(request, 'user', None)
    try:
        AccessAudit.objects.create(
            actor_id=normalize_user_id(user),
            actor_email=getattr(user, 'email', None),
            object_type=object_type,
            object_id=str(getattr(obj, 'pk', obj)),
            organization_id=getattr(obj, 'organization_id', None),
            event_type=event_type,
            decision=decision,
            metadata=metadata or {},
        )
        return True
    except Exception:
        return False


def _request_allowed_orgs(request):
    request_org_id = getattr(request, 'organization_id', None) if request is not None else None
    if request_org_id:
        # A validated selected organization is an active-workspace boundary.
        # Do not widen it back to every membership (NTS-51 review P1).
        return {request_org_id}
    return set(_user_org_ids(request))


def _permissions_at_least(minimum):
    return [role for role, rank in ROLE_ORDER.items() if rank >= ROLE_ORDER[minimum]]


def _active_owned_shares(request, *, object_type, minimum_role='view'):
    """Return active in-workspace Notebook/Tag grants for the caller."""
    from ..models import OwnedObjectShare

    user = getattr(request, 'user', None)
    user_id = normalize_user_id(user)
    user_email = getattr(user, 'email', None)
    allowed_orgs = _request_allowed_orgs(request)
    if not allowed_orgs or (user_id is None and not user_email):
        return OwnedObjectShare.objects.none()

    target = Q(shared_with_user_id=user_id)
    if user_email:
        target |= Q(shared_with_email=user_email)
    now = timezone.now()
    return OwnedObjectShare.objects.filter(
        target,
        object_type=object_type,
        organization_id__in=allowed_orgs,
        permission__in=_permissions_at_least(minimum_role),
        is_active=True,
        revoked_at__isnull=True,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))


def authorized_owned_filter(
    request, *, object_type, owner_field='created_by_id', minimum_role='view'
):
    """List/relation predicate for PER-USER owned objects (Notebook, Tag) — NTS-51.

    Owner | explicit active share, org-partitioned. Admin access is deliberately
    absent from bulk querysets: break-glass is explicit, per-object, and audited
    through ``can_access_owned``. Fails closed without validated org scope.
    """
    user_id = normalize_user_id(getattr(request, 'user', None))
    allowed_orgs = _request_allowed_orgs(request)
    if not allowed_orgs or user_id is None:
        return Q(pk__in=[])
    owner_q = Q(**{owner_field: user_id})
    shared_ids = _active_owned_shares(
        request, object_type=object_type, minimum_role=minimum_role
    ).filter(organization_id=OuterRef('organization_id')).values('object_id')
    return Q(organization_id__in=list(allowed_orgs)) & (
        owner_q | Q(pk__in=Subquery(shared_ids))
    )


def can_access_owned(
    request, obj, *, object_type, owner_field='created_by_id', minimum_role='view'
):
    """Object-level decision for a per-user owned object (Notebook/Tag).

    owner | active explicit share within org → allow. Privileged within org →
    break-glass only if the mandatory audit persists. Everything else denies.
    """
    try:
        user_id = normalize_user_id(getattr(request, 'user', None))
        org_id = getattr(obj, 'organization_id', None)
        allowed_orgs = _request_allowed_orgs(request)
        # Org partition: object must be in a workspace the caller can act in.
        if not allowed_orgs or org_id not in allowed_orgs:
            return AccessDecision(False)
        if getattr(obj, owner_field, None) == user_id and user_id is not None:
            return AccessDecision(True, 'edit', None, 'owner')

        shares = _active_owned_shares(
            request, object_type=object_type, minimum_role=minimum_role
        ).filter(object_id=obj.pk, organization_id=org_id)
        share = max(
            shares,
            key=lambda value: (ROLE_ORDER.get(value.permission, 0), value.created_at),
            default=None,
        )
        if share is not None:
            return AccessDecision(True, share.permission, share, 'share')

        if is_privileged(request):
            if record_break_glass(request, object_type=object_type, obj=obj):
                return AccessDecision(True, 'edit', None, 'break_glass')
            # Audit could not persist — deny the privileged access.
            return AccessDecision(False)
    except Exception:
        return AccessDecision(False)
    return AccessDecision(False)


def can_access(user_or_id, note_or_id, *, request=None, link_token=None):
    """Single fail-closed predicate for note access.

    Returns AccessDecision(role='edit' for owner; otherwise the active share role).
    Any lookup/evaluation error returns denied so callers can translate that to
    404 and avoid leaking note existence.
    """
    from ..models import Note

    user_id = normalize_user_id(user_or_id)
    if user_id is None:
        return AccessDecision(False, None, None)

    try:
        if isinstance(note_or_id, Note):
            note = note_or_id
        else:
            note = Note.objects.get(pk=note_or_id)

        # NTS-51 (revi round-5 P1): the OWNER leg must respect the selected-org
        # partition. The prior code returned owner/edit unconditionally, so a
        # request selected into workspace A reached a workspace-B note the caller
        # owns and a cross-workspace attachment POST persisted 201. Gate ONLY the
        # owner leg on the note's org (selected org only; memberships only in
        # explicit all-org mode). A cross-org SHARE legitimately has
        # note.org != selected org and carries its own _share_org_allowed boundary
        # below, so it is NOT gated here; break-glass likewise self-gates on the
        # note's org. org-less notes and request-less internal callers keep the
        # owner leg. On a cross-workspace owned note we fall through to the
        # share/break-glass legs rather than returning owner.
        note_org = getattr(note, 'organization_id', None)
        owner_in_selected_workspace = (
            request is None
            or not note_org
            or note_org in _request_allowed_orgs(request))
        if note.created_by_id == user_id and owner_in_selected_workspace:
            return AccessDecision(True, 'edit', None, 'owner')

        user_email = getattr(getattr(request, 'user', None), 'email', None)
        share_qs = _active_share_queryset().filter(note=note)
        user_q = Q(shared_with_user_id=user_id)
        if user_email:
            user_q |= Q(shared_with_email=user_email)
        if link_token:
            user_q |= Q(public_link_token=link_token, is_public_link=True)
        shares = [share for share in share_qs.filter(user_q) if _share_org_allowed(share, request)]
        if shares:
            share = max(shares, key=lambda s: (ROLE_ORDER.get(s.permission, 0), s.created_at))
            return AccessDecision(True, share.permission, share, 'share')

        # NTS-51: audited admin break-glass — org admin/owner/superuser may reach
        # an in-org note they neither own nor are shared on, but ONLY with a
        # persisted audit row; if the audit cannot be written, deny (fail closed).
        if request is not None and is_privileged(request):
            note_org = getattr(note, 'organization_id', None)
            if not note_org or note_org in _request_allowed_orgs(request):
                if record_break_glass(request, object_type='note', obj=note):
                    return AccessDecision(True, 'edit', None, 'break_glass')
                return AccessDecision(False, None, None)
    except Exception:
        return AccessDecision(False, None, None)

    return AccessDecision(False, None, None)


def has_role(decision: AccessDecision, minimum: str) -> bool:
    return bool(decision.allowed and ROLE_ORDER.get(decision.role or '', 0) >= ROLE_ORDER[minimum])


def record_audit(note, actor_id, event_type, *, share=None, target_user_id=None, role=None, metadata=None):
    """Best-effort durable audit event; never break user flow on audit failure."""
    from ..models import NoteShareAudit
    try:
        return NoteShareAudit.objects.create(
            note=note,
            actor_id=normalize_user_id(actor_id),
            event_type=event_type,
            share=share,
            target_user_id=target_user_id,
            role=role,
            metadata=metadata or {},
        )
    except Exception:
        return None
