"""NTS-36: minimal settings to run the authorization-invariant suite in CI.

Deliberately standalone (NOT importing notesmanager.settings) so the gate needs
no Postgres, Redis, JWT/allauth env, or log-dir scaffolding — it exercises the
authz predicate over the ORM/DRF layer only. sqlite + disabled migrations builds
the schema straight from model state (the notes app declares no CheckConstraint,
so this is faithful; the Postgres-specific search/GIN indexes are irrelevant to
the owner/tenant-scope predicate under test).

Run: DJANGO_SETTINGS_MODULE=notes.tests.authz_ci_settings \
     python manage.py test notes.tests.test_nts36_authz_invariants
"""
SECRET_KEY = 'nts36-authz-ci'
DEBUG = False
INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'django.contrib.postgres',
    'rest_framework',
    'notes.apps.NotesConfig',
]
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
USE_TZ = True
REST_FRAMEWORK = {}


class _DisableMigrations:
    def __contains__(self, item):
        return True

    def __getitem__(self, item):
        return None


MIGRATION_MODULES = _DisableMigrations()
