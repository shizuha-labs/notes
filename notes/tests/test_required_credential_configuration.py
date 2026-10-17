"""Production settings must receive credentials explicitly, including in debug mode."""
import importlib
import json
import os
from pathlib import Path
import secrets
import shlex
import subprocess
import sys
import unittest


class RequiredCredentialConfigurationTests(unittest.TestCase):
    def run_settings(self, overrides=None, removed=()):
        keys = {'JWT_SECRET_KEY', 'SECRET_KEY', 'POSTGRES_PASSWORD', 'DJANGO_SETTINGS_notesmanager.settings',
                'AWS_STORAGE_BUCKET_NAME', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY'}
        env = {key: value for key, value in os.environ.items() if key not in keys}
        env.update(SECRET_KEY=secrets.token_urlsafe(48), POSTGRES_PASSWORD=secrets.token_urlsafe(32), DEBUG='False')
        env.update(overrides or {})
        for key in removed:
            env.pop(key, None)
        program = """
import importlib
import json
import os
s = importlib.import_module("notesmanager.settings")
options = s.STORAGES["default"]["OPTIONS"] if os.environ.get("AWS_STORAGE_BUCKET_NAME") else None
print(json.dumps({
    "database_matches": s.DATABASES["default"]["PASSWORD"] == os.environ.get("POSTGRES_PASSWORD"),
    "signing_matches": s.SECRET_KEY == (os.environ.get("JWT_SECRET_KEY") or os.environ.get("SECRET_KEY")),
    "storage_matches": options is None or (
        options["access_key"] == os.environ["AWS_ACCESS_KEY_ID"] and
        options["secret_key"] == os.environ["AWS_SECRET_ACCESS_KEY"]),
}))
"""
        result = subprocess.run([sys.executable, '-c', program], cwd=Path(__file__).resolve().parents[2],
                                env=env, capture_output=True, text=True, timeout=30)
        return result

    def test_missing_or_blank_database_password_fails_closed_in_all_debug_modes(self):
        for debug in ('False', 'True'):
            for value in (None, '', ' \t '):
                with self.subTest(debug=debug, missing=value is None):
                    result = self.run_settings({'DEBUG': debug, **({'POSTGRES_PASSWORD': value} if value is not None else {})},
                                               removed=('POSTGRES_PASSWORD',) if value is None else ())
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('POSTGRES_PASSWORD must be configured', result.stderr)

    def test_whitespace_signing_key_never_uses_a_shared_identity(self):
        for debug in ('False', 'True'):
            for key in ('JWT_SECRET_KEY', 'SECRET_KEY'):
                with self.subTest(debug=debug, key=key):
                    result = self.run_settings({'DEBUG': debug, key: ' \t '})
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Set JWT_SECRET_KEY or SECRET_KEY', result.stderr)

    def test_explicit_values_and_jwt_precedence_are_preserved(self):
        for use_jwt in (False, True):
            values = {'POSTGRES_PASSWORD': '  ' + secrets.token_urlsafe(32) + '  '}
            if use_jwt:
                values['JWT_SECRET_KEY'] = secrets.token_urlsafe(48)
            result = self.run_settings(values)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {'database_matches': True, 'signing_matches': True, 'storage_matches': True})

    def test_static_collection_has_disposable_inline_database_configuration(self):
        root = Path(__file__).resolve().parents[2]
        lines = [line.removeprefix('RUN ') for line in (root / 'Dockerfile').read_text().splitlines()
                 if line.startswith('RUN ') and 'manage.py collectstatic' in line]
        self.assertEqual(len(lines), 1)
        tokens = shlex.split(lines[0])
        env = {name: os.environ[name] for name in ('PATH', 'HOME', 'LANG') if name in os.environ}
        while tokens and '=' in tokens[0]:
            name, value = tokens.pop(0).split('=', 1)
            env[name] = value
        self.assertEqual(tokens[:3], ['python', 'manage.py', 'collectstatic'])
        command = [sys.executable, *tokens[1:], '--dry-run']
        result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        env.pop('POSTGRES_PASSWORD', None)
        result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('POSTGRES_PASSWORD must be configured', result.stderr)

    def test_enabled_object_storage_requires_explicit_credential_pair(self):
        valid = {'AWS_STORAGE_BUCKET_NAME': 'fixture-notes', 'AWS_S3_ENDPOINT_URL': 'http://127.0.0.1:9',
                 'AWS_ACCESS_KEY_ID': secrets.token_hex(16), 'AWS_SECRET_ACCESS_KEY': secrets.token_urlsafe(32)}
        for key in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY'):
            for value in (None, '', ' \t '):
                with self.subTest(key=key, missing=value is None):
                    values = {**valid, **({key: value} if value is not None else {})}
                    result = self.run_settings(values, removed=(key,) if value is None else ())
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(key + ' must be configured', result.stderr)
        result = self.run_settings(valid)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['storage_matches'])

    def test_explicit_blank_jwt_does_not_select_secondary_signing_key(self):
        for debug in ('False', 'True'):
            for value in ('', ' \t '):
                with self.subTest(debug=debug, blank=value == ''):
                    result = self.run_settings({'DEBUG': debug, 'JWT_SECRET_KEY': value})
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Set JWT_SECRET_KEY or SECRET_KEY', result.stderr)
