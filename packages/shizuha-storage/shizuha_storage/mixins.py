"""
Django view mixins for quota-tracked file uploads.

Provides QuotaTrackingMixin that can be added to DRF ViewSets
to automatically check quota before upload and report usage after.
"""
import logging
from django.conf import settings
from rest_framework.exceptions import ValidationError
from .quota import StorageQuotaClient

logger = logging.getLogger(__name__)


def get_quota_client():
    """Get a configured StorageQuotaClient from Django settings."""
    service_name = getattr(settings, 'STORAGE_QUOTA_SERVICE', None)
    drive_url = getattr(settings, 'STORAGE_DRIVE_URL', 'http://shizuha-drive:8018')
    if not service_name:
        return None
    return StorageQuotaClient(service_name, drive_url)


def calculate_service_usage(model_class, file_field_name='file', size_field_name=None):
    """
    Calculate total storage usage for a model with file fields.

    Args:
        model_class: The Django model class
        file_field_name: Name of the FileField on the model
        size_field_name: Name of an explicit size field (if any), otherwise calculated from file
    """
    from django.db.models import Sum, Count

    if size_field_name:
        stats = model_class.objects.aggregate(
            total_bytes=Sum(size_field_name),
            total_count=Count('id'),
        )
    else:
        # If no size field, we can't sum efficiently — count only
        stats = {'total_bytes': 0, 'total_count': model_class.objects.count()}

    return {
        'used_bytes': stats.get('total_bytes') or 0,
        'file_count': stats.get('total_count') or 0,
    }
