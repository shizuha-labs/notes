# Explicit installation credentials

Set `JWT_SECRET_KEY` or `SECRET_KEY` and `POSTGRES_PASSWORD` before starting the
service, including when `DEBUG` is enabled. Empty or whitespace-only values are
refused; a present JWT key takes precedence, and a blank selected key is refused. Static image collection supplies
its own disposable inline build configuration, and isolated SQLite test settings
use disposable test configuration rather than production credential defaults.

Object storage remains optional. Setting `AWS_STORAGE_BUCKET_NAME` enables it and
requires both `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`; filesystem mode
does not require object-store credentials.
