"""Exercise the cluster-bootstrap workflow step without downloading tools."""
import base64
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class ToolboxBootstrapTests(unittest.TestCase):
    def test_existing_pinned_client_and_private_cluster_config(self):
        workflow = (Path(__file__).parents[1] / 'workflows/deploy.yml').read_text()
        section = workflow.split('name: Verify CI toolbox + configure cluster access\n', 1)[1]
        raw = section.split('run: |\n', 1)[1].split('      - name:', 1)[0]
        script = '\n'.join(line[10:] for line in raw.splitlines())
        self.assertNotIn('curl ', script)
        self.assertNotIn('wget ', script)
        self.assertIn('@sha256:', workflow.split('steps:')[0])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = root / 'kubectl'
            client.write_text('#!/bin/sh\n[ "$*" = "version --client=true" ] || exit 20\nprintf verified > "$TEST_CONFIG_ROOT/client-verified"\n')
            client.chmod(0o755)
            configuration = b'apiVersion: v1\nkind: Config\n'
            script = script.replace('${{ secrets.KUBE_CONFIG_B64 }}', base64.b64encode(configuration).decode())
            script = script.replace('$HOME/.kube', '$TEST_CONFIG_ROOT/kube')
            environment = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'], TEST_CONFIG_ROOT=str(root))
            subprocess.run(['bash', '-euo', 'pipefail', '-c', script], env=environment, check=True)
            self.assertTrue((root / 'client-verified').is_file())
            self.assertEqual((root / 'kube/config').read_bytes(), configuration)
            self.assertEqual((root / 'kube/config').stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
