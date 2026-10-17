"""Exercise the actual contents-API CAS conflict and refetch through HTTP."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('persist_frontend', Path(__file__).with_name('persist-frontend-tag.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class FrontendTagConflictTest(unittest.TestCase):
    def run_server(self, detail):
        calls = []
        original = 'replicaCount: 2\nfrontend:\n  image:\n    tag: notes-frontend-aaaaaaa\n'
        updated = original.replace('replicaCount: 2', 'replicaCount: 3')
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                current = updated if calls else original
                body = json.dumps({'sha': 'new' if calls else 'old', 'content': base64.b64encode(current.encode()).decode()}).encode()
                self.send_response(200); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
            def do_PUT(self):
                calls.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                code = 500 if len(calls) == 1 else 200
                body = json.dumps({'message': detail}).encode()
                self.send_response(code); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
            def log_message(self,*args): pass
        server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker = threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            with patch.dict(os.environ, {'FORGEJO_API_URL': f'http://127.0.0.1:{server.server_port}', 'DEPLOY_PUSH_TOKEN':'test-only', 'VERIFIED_FRONTEND_TAG':'notes-frontend-bbbbbbb'}), patch.object(module.time,'sleep'):
                module.main()
        finally:
            server.shutdown();server.server_close();worker.join()
        return calls

    def test_concurrent_branch_write_refetches_and_preserves_other_fields(self):
        calls = self.run_server('PushRejected Error: incorrect old value provided')
        self.assertEqual([x['sha'] for x in calls],['old','new'])
        content = base64.b64decode(calls[-1]['content']).decode()
        self.assertIn('replicaCount: 3',content)
        self.assertIn('tag: notes-frontend-bbbbbbb',content)

    def test_unrelated_server_error_is_not_retried(self):
        with self.assertRaisesRegex(RuntimeError,'HTTP 500'):
            self.run_server('repository storage unavailable')

class TagPersistenceTests(unittest.TestCase):
    def test_preserves_backend_and_other_tags(self):
        source = 'image:\n  tag: backend-old\nfrontend:\n  enabled: true\n  image:\n    tag: frontend-old\n  replicas: 2\nother:\n  tag: other-old\n'
        result = module.update_tag(source, 'notes-frontend-96dc0e8')
        self.assertEqual(result.replace('notes-frontend-96dc0e8', 'frontend-old'), source)

    def test_missing_or_ambiguous_frontend_tag_fails_closed(self):
        for source in ['image:\n  tag: old\n', 'frontend:\n  enabled: true\n', 'frontend:\n    tag: one\n    tag: two\n']:
            with self.assertRaises(ValueError):
                module.update_tag(source, 'notes-frontend-96dc0e8')

    def test_rejects_unverified_tag_shapes(self):
        for tag in ['latest', 'notes-frontend-xyz', 'notes-frontend-96dc0e8\n']:
            with self.assertRaises(ValueError):
                module.update_tag('frontend:\n    tag: old\n', tag)


if __name__ == '__main__': unittest.main()
