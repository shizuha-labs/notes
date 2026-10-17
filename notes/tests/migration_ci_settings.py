"""Isolated PostgreSQL profile for real historical migration tests."""
import os

SECRET_KEY = os.environ['SECRET_KEY']
DEBUG = False
INSTALLED_APPS = ['django.contrib.auth','django.contrib.contenttypes','django.contrib.postgres','notes.apps.NotesConfig']
DATABASES = {'default':{
    'ENGINE':'django.db.backends.postgresql',
    'NAME':os.environ.get('POSTGRES_DB','notes_migration_ci'),
    'USER':os.environ.get('POSTGRES_USER','postgres'),
    'PASSWORD':os.environ['POSTGRES_PASSWORD'],
    'HOST':os.environ.get('POSTGRES_HOST','127.0.0.1'),
    'PORT':os.environ.get('POSTGRES_PORT','5432'),
    'TEST':{'NAME':os.environ.get('NOTES_MIGRATION_TEST_DATABASE','test_notes_legacy_mapping_ci')},
}}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
USE_TZ = True
