"""Exercise the pre-checkout artifact and PostgreSQL-major boundaries in CI."""
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


def bootstrap_source():
    workflow = (ROOT / '.forgejo/workflows/authz-invariant-check.yml').read_text()
    start = workflow.index("          python3 - <<'PYTHON'\n")
    end = workflow.index('\n          PYTHON', start)
    return '\n'.join(line[10:] for line in workflow[start:end].splitlines()[1:])


class NativeCiEnvironmentTests(unittest.TestCase):
    def test_bookworm_bootstrap_precedes_checkout(self):
        workflow = (ROOT / '.forgejo/workflows/authz-invariant-check.yml').read_text()
        self.assertIn('python@sha256:581429e3df12d76e6af4be5ab7d0e7fc2013eb57dc23d2de691411c8efdbb970', workflow)
        self.assertLess(workflow.index('Bootstrap hash-pinned checkout Node'), workflow.index('uses: actions/checkout@v4'))
        compile(bootstrap_source(), '<native Node bootstrap>', 'exec')

    def test_container_job_explicitly_selects_shell_for_its_real_preamble(self):
        import re
        workflow = (ROOT / '.forgejo/workflows/authz-invariant-check.yml').read_text()
        declared = re.search(r'^    defaults:\n      run:\n        shell: ([^\n]+)', workflow, re.MULTILINE)
        # Native run635 used sh for an unspecified container shell. Execute the
        # actual first command under the selected interpreter before asserting.
        shell = declared.group(1) if declared else 'sh'
        result = subprocess.run([shell, '-c', 'set -euo pipefail\nprintf shell-contract-ok'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNotNone(declared)
        self.assertEqual(result.stdout, 'shell-contract-ok')

    def test_unknown_architecture_refuses_before_network_or_installation(self):
        with patch('platform.machine', return_value='unreviewed'), \
             patch('urllib.request.build_opener') as opener, patch('builtins.open') as output:
            with self.assertRaisesRegex(SystemExit, 'Unsupported'):
                exec(bootstrap_source(), {})
        opener.assert_not_called()
        output.assert_not_called()

    def test_corrupt_artifact_refuses_both_architectures_before_installation(self):
        for machine in ('x86_64', 'aarch64'):
            with self.subTest(machine=machine), patch('platform.machine', return_value=machine), \
                 patch('urllib.request.build_opener') as opener, patch('builtins.open') as output:
                opener.return_value.open.return_value.__enter__.return_value = io.BytesIO(b'untrusted archive')
                with self.assertRaisesRegex(SystemExit, 'digest mismatch'):
                    exec(bootstrap_source(), {})
                url = opener.return_value.open.call_args.args[0]
                self.assertTrue(url.startswith('http://forgejo-http.origin.svc.cluster.local/api/packages/actions/generic/node/v22.14.0/'))
                output.assert_not_called()

    def test_pg_gate_refuses_unready_or_wrong_major(self):
        workflow = (ROOT / '.forgejo/workflows/authz-invariant-check.yml').read_text()
        commands = '\n'.join(line.strip() for line in workflow.splitlines()
                             if line.strip().startswith(('pg_isready ', 'test "$(su postgres')))
        self.assertEqual(len(commands.splitlines()), 3)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in {'pg_isready': 'exit "${PG_READY:-0}"',
                                  'su': 'printf "%s\\n" "$PG_VERSION"'}.items():
                target = root / name
                target.write_text('#!/bin/sh\n' + content + '\n')
                target.chmod(0o700)
            import os
            for version, ready, expected in [('150019', '0', 0), ('140020', '0', 1),
                                             ('160000', '0', 1), ('150019', '1', 1)]:
                with self.subTest(version=version, ready=ready):
                    env = dict(os.environ, PATH=f'{directory}:' + os.environ['PATH'],
                               PG_VERSION=version, PG_READY=ready)
                    result = subprocess.run(['bash', '-euo', 'pipefail', '-c', commands], env=env,
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, expected == 0)
