"""Use an external endpoint only for presigning, never for object IO."""
from urllib.parse import urlsplit
from storages.backends.s3 import S3Storage


class PublicEndpointS3Storage(S3Storage):
    def __init__(self, public_endpoint, **options):
        parsed = urlsplit(public_endpoint)
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {'', '/'}):
            raise ValueError('S3 public endpoint must be an HTTP(S) origin without credentials')
        super().__init__(**options)
        # Django settings also supply defaults; validate the resolved backend,
        # not only explicitly supplied constructor options.
        if self.custom_domain or not self.querystring_auth:
            raise ValueError('S3 public endpoint requires signed URLs without a custom domain')
        # A separate backend preserves boto's canonical signing and all URL
        # options. No URL rewriting and no mutation of the internal connection.
        self._public_signer = S3Storage(**{**options, 'endpoint_url': public_endpoint.rstrip('/')})

    def url(self, name, parameters=None, expire=None, http_method=None):
        return self._public_signer.url(name, parameters=parameters, expire=expire, http_method=http_method)
