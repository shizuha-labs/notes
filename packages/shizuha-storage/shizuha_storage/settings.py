"""
Reusable MinIO/S3 storage settings for Django services.

Usage in a service's settings.py:

    from shizuha_storage.settings import get_minio_storage_settings

    STORAGES = get_minio_storage_settings(
        bucket_name=os.environ.get('AWS_STORAGE_BUCKET_NAME', 'shizuha-wiki'),
        endpoint=os.environ.get('AWS_S3_ENDPOINT_URL', 'http://minio:9000'),
        access_key=os.environ.get('AWS_ACCESS_KEY_ID'),
        secret_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
    )
"""

import os

def get_minio_storage_settings(bucket_name, endpoint='http://minio:9000',
                                access_key=None, secret_key=None,
                                querystring_auth=True, url_protocol='http:',
                                custom_domain=None, public_endpoint=None):
    """
    Return Django STORAGES dict for S3Boto3Storage (MinIO-compatible).

    Args:
        bucket_name: The MinIO bucket name (e.g. 'shizuha-wiki')
        endpoint: MinIO endpoint URL (e.g. 'http://minio:9000')
        access_key: Explicit nonblank MinIO access key (required)
        secret_key: Explicit nonblank MinIO secret key (required)
        querystring_auth: Whether to use query string auth for URLs
        url_protocol: Protocol for generated URLs
        custom_domain: Optional custom domain for file URLs
        public_endpoint: External origin for signed URLs, with internal object IO
            unchanged. Defaults to AWS_S3_PUBLIC_ENDPOINT_URL when configured.
    """
    # Calling this factory enables authenticated S3 storage. Never invent a
    # shared account or fall through to an SDK's ambient credential sources.
    for name, value in (('access_key', access_key), ('secret_key', secret_key)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'{name} must be configured')
    public_endpoint = public_endpoint or os.environ.get('AWS_S3_PUBLIC_ENDPOINT_URL')
    options = {'public_endpoint': public_endpoint} if public_endpoint else {}
    return {
        "default": {
            "BACKEND": ("shizuha_storage.backends.PublicEndpointS3Storage" if public_endpoint
                        else "storages.backends.s3boto3.S3Boto3Storage"),
            "OPTIONS": {
                **options,
                "access_key": access_key,
                "secret_key": secret_key,
                "bucket_name": bucket_name,
                "endpoint_url": endpoint,
                "addressing_style": "path",
                "signature_version": "s3v4",
                "querystring_auth": querystring_auth,
                "url_protocol": url_protocol,
                "custom_domain": custom_domain,
                "file_overwrite": False,
                "default_acl": None,
            },
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
