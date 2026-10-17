"""Execute the image entrypoint without provisioning any local administrator."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class EntrypointBootstrapTest(unittest.TestCase):
    def test_startup_migrates_and_serves_without_creating_an_account(self):
        source = Path(__file__).resolve().parents[2] / 'docker-entrypoint.sh'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = root / 'calls.jsonl'
            for command in ('nc', 'pip'):
                path = root / command
                path.write_text('#!/bin/sh\nexit 0\n')
                path.chmod(0o700)
            recorder = f'''#!{sys.executable}
import json, os, pathlib, sys
arguments = sys.argv[1:] if pathlib.Path(sys.argv[0]).name == 'python' else ['serve'] + sys.argv[1:]
with open(os.environ['ENTRYPOINT_CALLS'], 'a') as output:
    output.write(json.dumps(arguments) + '\\n')
# An implicit account-creation shell is forbidden even if it would be idempotent.
if 'shell' in arguments or 'createsuperuser' in arguments:
    raise SystemExit(73)
'''
            for command in ('python', 'serve'):
                path = root / command
                path.write_text(recorder)
                path.chmod(0o700)
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                       ENTRYPOINT_CALLS=str(calls), POSTGRES_HOST='isolated.invalid')
            result = subprocess.run(['bash', str(source), str(root / 'serve'), '--check'],
                                    env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual([json.loads(line) for line in calls.read_text().splitlines()], [
                ['manage.py', 'createdb'], ['manage.py', 'migrate', '--noinput'],
                ['manage.py', 'collectstatic', '--noinput'], ['serve', '--check'],
            ])
