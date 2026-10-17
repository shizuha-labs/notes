"""Actual Notes image writers must publish an actionable Deploy Git commit.

Forgejo SKIP_WORKFLOW_STRINGS suppresses push workflows before path selection:
https://forgejo.org/docs/latest/admin/config-cheat-sheet/#actions-actions
Only synthetic loopback contents APIs and owned temporary Git repositories run.
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
VALUES = 'k3s/charts/shizuha-notes/values.yaml'
SKIP_STRINGS = ('[skip ci]', '[ci skip]', '[no ci]', '[skip actions]', '[actions skip]')
ORIGINAL = 'replicaCount: 2\nimage:\n  tag: notes-0000000\nfrontend:\n  image:\n    tag: notes-frontend-0000000\n'


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True,
        stderr=subprocess.PIPE, env={**os.environ, 'GIT_CONFIG_NOSYSTEM': '1',
        'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_AUTHOR_NAME': 'Fixture',
        'GIT_AUTHOR_EMAIL': 'fixture@example.invalid', 'GIT_COMMITTER_NAME': 'Fixture',
        'GIT_COMMITTER_EMAIL': 'fixture@example.invalid'}).strip()


def backend_publication_body():
    lines = (ROOT / '.forgejo/workflows/deploy.yml').read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith('# Auto-update values.yaml in deploy repo'))
    body = []
    for line in lines[start:]:
        if line and not line.startswith(' ' * 10):
            break
        body.append(line[10:])
    source = '\n'.join(body).replace('${{ secrets.DEPLOY_PUSH_TOKEN }}', 'synthetic-only')
    if '${{' in source:
        raise AssertionError('unrecognized workflow expression in actual publication caller')
    return 'set -euo pipefail\n' + source + '\n'


class DeployOwnerEventDeliveryTests(unittest.TestCase):
    def publish(self, writer, *, repeat=False):
        with tempfile.TemporaryDirectory(prefix='notes-deploy-event-') as directory:
            root = Path(directory); repo = root / 'deploy'; repo.mkdir()
            git(repo, 'init', '-q', '-b', 'master')
            path = repo / VALUES; path.parent.mkdir(parents=True); path.write_text(ORIGINAL)
            git(repo, 'add', VALUES); git(repo, 'commit', '-qm', 'Initial synthetic deployment values')
            before = git(repo, 'rev-parse', 'HEAD'); calls = []
            class Handler(BaseHTTPRequestHandler):
                def do_GET(self):
                    if unquote(urlsplit(self.path).path) != '/api/v1/repos/shizuha-labs/deploy/contents/' + VALUES:
                        self.send_error(404); return
                    data = json.dumps({'sha': git(repo, 'rev-parse', 'HEAD:' + VALUES),
                        'content': base64.b64encode(path.read_bytes()).decode()}).encode()
                    self.send_response(200); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
                def do_PUT(self):
                    payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    if payload['sha'] != git(repo, 'rev-parse', 'HEAD:' + VALUES):
                        self.send_error(409); return
                    calls.append(payload); path.write_bytes(base64.b64decode(payload['content'], validate=True))
                    git(repo, 'add', VALUES); git(repo, 'commit', '-qm', payload['message'])
                    self.send_response(200); self.send_header('Content-Length', '2'); self.end_headers(); self.wfile.write(b'{}')
                def log_message(self, *args): pass
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
            endpoint = f'http://127.0.0.1:{server.server_port}'
            env = {**os.environ, 'FORGEJO_API_URL': endpoint + '/api/v1',
                'DEPLOY_PUSH_TOKEN': 'synthetic-only', 'VERIFIED_FRONTEND_TAG': 'notes-frontend-1111111',
                'TAG': 'notes-1111111', 'FIXTURE_CONTENTS_ENDPOINT': endpoint}
            try:
                if writer == 'frontend':
                    result = subprocess.run([sys.executable, str(ROOT / '.forgejo/scripts/persist-frontend-tag.py')],
                        env=env, capture_output=True, text=True, timeout=15)
                else:
                    binaries = root / 'bin'; binaries.mkdir()
                    (binaries / 'kubectl').write_text('#!/bin/sh\n[ "$*" = "get svc forgejo-http -n origin -o jsonpath={.spec.clusterIP}" ] || exit 2\nprintf 127.0.0.1\n')
                    (binaries / 'curl').write_text('''#!/usr/bin/env python3
import os,sys,urllib.request,urllib.parse
args=sys.argv[1:];url=next(x for x in args if x.startswith('http://'))
u=urllib.parse.urlsplit(url)
assert u.netloc=='127.0.0.1:80' and urllib.parse.unquote(u.path)=='/api/v1/repos/shizuha-labs/deploy/contents/k3s/charts/shizuha-notes/values.yaml'
headers={}
for i,x in enumerate(args):
 if x=='-H':
  k,v=args[i+1].split(':',1);headers[k]=v.strip()
data=args[args.index('-d')+1].encode() if '-d' in args else None
op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
with op.open(urllib.request.Request(os.environ['FIXTURE_CONTENTS_ENDPOINT']+u.path,headers=headers,data=data,method='PUT' if data else 'GET'),timeout=5) as r:
 sys.stdout.buffer.write(r.read())
''')
                    for file in binaries.iterdir(): file.chmod(0o700)
                    env['PATH'] = str(binaries) + os.pathsep + env['PATH']
                    result = subprocess.run(['bash', '-c', backend_publication_body()], env=env,
                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(calls), 1)
                changed = git(repo, 'diff', '--name-only', before, 'HEAD').splitlines()
                message = git(repo, 'show', '-s', '--format=%B', 'HEAD')
                self.assertEqual(changed, [VALUES])
                expected = ORIGINAL.replace('notes-frontend-0000000', 'notes-frontend-1111111') if writer == 'frontend' else ORIGINAL.replace('tag: notes-0000000', 'tag: notes-1111111')
                self.assertEqual(path.read_text().strip(), expected.strip())
                if repeat:
                    head = git(repo, 'rev-parse', 'HEAD')
                    again = subprocess.run([sys.executable, str(ROOT / '.forgejo/scripts/persist-frontend-tag.py')], env=env, capture_output=True, text=True, timeout=15)
                    self.assertEqual(again.returncode, 0, again.stderr)
                    self.assertEqual(git(repo, 'rev-parse', 'HEAD'), head)
                    self.assertEqual(len(calls), 1)
                return message, changed
            finally:
                server.shutdown(); server.server_close(); worker.join()

    def test_frontend_actual_contents_commit_remains_eligible_for_deploy_owner(self):
        message, _ = self.publish('frontend')
        self.assertFalse(any(marker in message.lower() for marker in SKIP_STRINGS), message)

    def test_backend_actual_workflow_contents_commit_remains_eligible_for_deploy_owner(self):
        message, _ = self.publish('backend')
        self.assertFalse(any(marker in message.lower() for marker in SKIP_STRINGS), message)

    def test_frontend_already_current_tag_does_not_create_another_commit(self):
        self.publish('frontend', repeat=True)
