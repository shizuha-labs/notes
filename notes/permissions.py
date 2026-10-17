"""
Permission classes for Shizuha Notes.
"""
from rest_framework import permissions
from .models import Note
from .services.access import can_access, has_role, can_access_owned


class ServiceAccessPermission(permissions.BasePermission):
    SERVICE_SLUG = 'notes'
    message = 'You do not have access to this service.'

    def has_permission(self, request, view):
        user = request.user
        if not hasattr(user, 'enabled_services'):
            return True  # Not a federated user (e.g., Django admin)
        if user.enabled_services is None:
            return True  # Unrestricted (staff/superuser)
        return self.SERVICE_SLUG in user.enabled_services


class OwnedObjectGetMixin:
    """NTS-51: single ACL entry point for per-user Notebook/Tag detail access —
    owner | explicit share | audited admin break-glass, org-partitioned,
    PREFER-404.

    Object access is decided exactly once here (one audit row on break-glass).
    Safe methods require view; mutations require edit. The viewset sets
    ``owned_object_type`` so the generic durable-grant table cannot cross types.
    """
    def get_object(self):
        lookup = self.kwargs.get(self.lookup_field or 'pk')
        model = self.get_queryset().model
        try:
            obj = model.objects.get(pk=lookup)
        except (model.DoesNotExist, ValueError, TypeError):
            _raise_owned_not_found()
        object_type = getattr(self, 'owned_object_type', None) or model.__name__.lower()
        minimum_role = 'view' if self.request.method in permissions.SAFE_METHODS else 'edit'
        decision = can_access_owned(
            self.request, obj, object_type=object_type, minimum_role=minimum_role
        )
        if not decision.allowed:
            _raise_owned_not_found()
        return obj

    def container_for_notes(self, pk):
        """Resolve a Notebook/Tag as a NOTES-LISTING container (the `{id}/notes/`
        sub-action). NTS-50 classifies these routes as note-content surfaces:
        the container is selected-org scoped here and the caller intersects its
        notes with the canonical note ACL. This preserves access to a note shared
        into somebody else's notebook/tag without exposing private note content.
        """
        model = self.get_queryset().model
        try:
            obj = model.objects.get(pk=pk)
        except (model.DoesNotExist, ValueError, TypeError):
            _raise_owned_not_found()
        from .services.access import _request_allowed_orgs
        if getattr(obj, 'organization_id', None) not in _request_allowed_orgs(self.request):
            _raise_owned_not_found()
        return obj


def _raise_owned_not_found():
    from rest_framework.exceptions import NotFound
    raise NotFound({'detail': 'Not found.'})


class IsNoteOwnerOrOrgMember(permissions.BasePermission):
    """
    NTS-3 note access predicate.

    Despite the historical class name, note content access is now owner ∪ active
    non-expired share. The org boundary is enforced on shares by `can_access()`;
    org membership alone does not reveal another user's note content/existence.
    """
    def has_object_permission(self, request, view, obj):
        if not isinstance(obj, Note):
            return False
        decision = can_access(request.user, obj, request=request)
        if request.method in permissions.SAFE_METHODS:
            return decision.allowed
        if getattr(view, 'action', None) == 'comments' and request.method == 'POST':
            return has_role(decision, 'comment')
        return has_role(decision, 'edit')


class CanEditNote(permissions.BasePermission):
    """
    Check if user can edit a specific note.
    """
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        if not isinstance(obj, Note):
            return True  # Not a note, let other permissions handle it
        return has_role(can_access(request.user, obj, request=request), 'edit')
