import logging
import os

import jwt as pyjwt
import requests
from django.conf import settings
from django.http import JsonResponse

logger = logging.getLogger(__name__)


class ServiceAccessMiddleware:
    SERVICE_SLUG = 'notes'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith('/api/'):
            return self.get_response(request)
        if '/internal/' in request.path:
            return self.get_response(request)

        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            try:
                payload = pyjwt.decode(
                    token,
                    getattr(settings, 'JWT_SECRET_KEY', settings.SECRET_KEY),
                    algorithms=['HS256'],
                    options={'verify_exp': True}
                )
                if payload.get('is_staff') or payload.get('is_superuser'):
                    return self.get_response(request)
                enabled_services = payload.get('enabled_services')
                if enabled_services is not None and self.SERVICE_SLUG not in enabled_services:
                    return JsonResponse(
                        {'error': 'You do not have access to this service.',
                         'service': self.SERVICE_SLUG,
                         'code': 'service_access_denied'},
                        status=403
                    )
            except Exception:
                pass  # Let DRF authentication handle invalid tokens

        return self.get_response(request)


class OrganizationContextMiddleware:
    """
    Extract organization from X-Organization-ID header.

    Note: This middleware only extracts the org ID from the header. The actual
    validation happens via the permission classes after DRF authentication.
    Django middleware runs before DRF authentication, so we can't validate
    membership here.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Just extract the org_id from the header - validation happens later
        org_id = request.META.get('HTTP_X_ORGANIZATION_ID')
        try:
            request._pending_organization_id = int(org_id) if org_id else None
        except (ValueError, TypeError):
            request._pending_organization_id = None
        return self.get_response(request)


def check_organization_membership(user_id, org_id, email=None):
    """
    Check if user is a member of the organization via shizuha-admin internal API.

    Returns dict with 'is_member' and 'role' if member, None otherwise.
    """
    skip_validation = os.environ.get('SKIP_ORG_VALIDATION', '').lower() == 'true'
    if skip_validation:
        return {'is_member': True, 'role': 'admin'}

    admin_url = os.environ.get('SHIZUHA_ADMIN_API_URL', 'http://shizuha-admin:8003/api')
    try:
        params = {'email': email} if email else {}
        response = requests.get(
            f'{admin_url}/internal/organizations/{org_id}/members/{user_id}/',
            params=params,
            timeout=5
        )
        if response.status_code == 200:
            return response.json()
        logger.debug(f"Membership check failed: {response.status_code}")
    except requests.RequestException as e:
        logger.warning(f"Failed to check organization membership: {e}")
    except Exception as e:
        logger.error(f"Unexpected error checking membership: {e}")
    return None


def get_user_organization_ids(request):
    """
    Get all organization IDs the user is a member of.

    Caches on the request object to avoid repeated API calls within a single request.
    Returns a list of org IDs, or None on failure.
    """
    if hasattr(request, '_user_organization_ids'):
        return request._user_organization_ids

    skip_validation = os.environ.get('SKIP_ORG_VALIDATION', '').lower() == 'true'
    if skip_validation:
        request._user_organization_ids = None
        return None

    user = request.user
    if not user or not user.is_authenticated:
        request._user_organization_ids = []
        return []

    admin_url = os.environ.get('SHIZUHA_ADMIN_API_URL', 'http://shizuha-admin:8003/api')
    try:
        params = {}
        email = getattr(user, 'email', None)
        if email:
            params['email'] = email
        response = requests.get(
            f'{admin_url}/internal/users/{user.id}/organizations/',
            params=params,
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            org_ids = [org['id'] for org in data.get('organizations', [])]
            request._user_organization_ids = org_ids
            return org_ids
    except requests.RequestException as e:
        logger.warning(f"Failed to fetch user organizations: {e}")
    except Exception as e:
        logger.error(f"Unexpected error fetching user organizations: {e}")

    request._user_organization_ids = []
    return []


def set_organization_context(request):
    """
    Set organization context on request after DRF authentication.
    Called from permission classes or view initialization.
    """
    if hasattr(request, 'organization_id'):
        return  # Already set

    org_id = getattr(request, '_pending_organization_id', None)
    if org_id is None:
        request.organization_id = None
        request.organization_role = None
        return

    if not request.user or not request.user.is_authenticated:
        request.organization_id = None
        request.organization_role = None
        return

    membership = check_organization_membership(
        request.user.id,
        org_id,
        getattr(request.user, 'email', None)
    )

    if membership and membership.get('is_member'):
        request.organization_id = org_id
        request.organization_role = membership.get('role')
        # Also set on user object if it supports it
        if hasattr(request.user, 'organization_id'):
            request.user.organization_id = org_id
        if hasattr(request.user, 'organization_role'):
            request.user.organization_role = membership.get('role')
    else:
        request.organization_id = None
        request.organization_role = None
