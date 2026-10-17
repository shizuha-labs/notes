"""
Storage quota client for cross-service quota tracking.

Reports storage usage to shizuha-drive's internal API and checks
whether a user has enough quota before allowing uploads.
"""
import logging
import requests

logger = logging.getLogger(__name__)


class StorageQuotaClient:
    """
    Client for communicating with shizuha-drive's internal storage API.

    Usage:
        client = StorageQuotaClient('wiki', 'http://shizuha-drive:8018')

        # Check before upload
        if client.can_upload(user_jwt, file_size=1024000):
            # proceed with upload
            ...

        # Report usage after upload/delete
        client.report_usage(user_jwt, used_bytes=total, file_count=count)
    """

    def __init__(self, service_name, drive_url='http://shizuha-drive:8018'):
        self.service_name = service_name
        self.drive_url = drive_url.rstrip('/')
        self.timeout = 5

    def _headers(self, user_jwt):
        return {
            'Authorization': f'Bearer {user_jwt}',
            'Content-Type': 'application/json',
        }

    def _extract_jwt(self, request):
        """Extract JWT token from a Django request object."""
        auth = request.META.get('HTTP_AUTHORIZATION', '')
        if auth.startswith('Bearer '):
            return auth[7:]
        return None

    def can_upload(self, user_jwt, file_size):
        """
        Check if user has enough quota for a file of given size.

        Returns True if allowed, False otherwise.
        On error (e.g. Drive unreachable), returns True to avoid blocking uploads.
        """
        try:
            resp = requests.post(
                f'{self.drive_url}/api/internal/storage/can-upload/',
                json={'file_size': file_size},
                headers=self._headers(user_jwt),
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                return resp.json().get('allowed', True)
            logger.warning(
                f"Quota check returned {resp.status_code}: {resp.text[:200]}"
            )
            return True  # fail open
        except Exception as e:
            logger.warning(f"Quota check failed (allowing upload): {e}")
            return True  # fail open

    def can_upload_from_request(self, request, file_size):
        """Convenience: extract JWT from Django request and check quota."""
        jwt = self._extract_jwt(request)
        if not jwt:
            return True  # can't check, fail open
        return self.can_upload(jwt, file_size)

    def report_usage(self, user_jwt, used_bytes, file_count):
        """
        Report current storage usage for this service to Drive.

        Should be called after successful upload or delete.
        """
        try:
            resp = requests.post(
                f'{self.drive_url}/api/internal/storage/report/',
                json={
                    'service': self.service_name,
                    'used_bytes': used_bytes,
                    'file_count': file_count,
                },
                headers=self._headers(user_jwt),
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                logger.warning(
                    f"Usage report returned {resp.status_code}: {resp.text[:200]}"
                )
        except Exception as e:
            logger.warning(f"Usage report failed: {e}")

    def report_usage_from_request(self, request, used_bytes, file_count):
        """Convenience: extract JWT from Django request and report usage."""
        jwt = self._extract_jwt(request)
        if jwt:
            self.report_usage(jwt, used_bytes, file_count)
