"""Exercise the security workflow's uv boundary under the native runner environment."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class AuthzDependencyEnvironmentTests(unittest.TestCase):
    def test_locked_sync_keeps_the_committed_registry_identity(self):
        root = Path(__file__).resolve().parents[2]
        workflow = (root / '.forgejo/workflows/authz-invariant-check.yml').read_text()
        commands = [line.strip() for line in workflow.splitlines()
                    if '.venv/bin/uv sync --locked --no-dev --no-install-project' in line]
        self.assertEqual(len(commands), 1)
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / '.venv/bin').mkdir(parents=True)
            uv = work / '.venv/bin/uv'
            uv.write_text('#!/usr/bin/env python3\nimport json, os, sys\n'
                          'keys=("UV_DEFAULT_INDEX","UV_INDEX_URL","UV_INSECURE_HOST")\n'
                          'assert not any(key in os.environ for key in keys), "runner changed lock registry"\n'
                          'assert sys.argv[1:]==["sync","--locked","--no-dev","--no-install-project"]\n'
                          'assert os.environ["UV_PROJECT_ENVIRONMENT"]==".venv"\n'
                          'print(json.dumps({"locked":True}))\n')
            uv.chmod(0o700)
            env = dict(os.environ, UV_DEFAULT_INDEX='http://cache.example.invalid/simple/',
                       UV_INDEX_URL='http://cache.example.invalid/simple/', UV_INSECURE_HOST='cache.example.invalid')
            result = subprocess.run(['bash', '-euo', 'pipefail', '-c', commands[0]],
                                    cwd=work, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {'locked': True})
