"""The build's real Django startup needs disposable process-local configuration."""
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('notes_image_bytecode_configuration', ROOT/'scripts/verify-image-bytecode.py')
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


class ImageBytecodeConfigurationTests(unittest.TestCase):
    def test_real_startup_probe_needs_no_inherited_credentials(self):
        with patch.dict(os.environ):
            for key in ('SECRET_KEY','JWT_SECRET_KEY','POSTGRES_PASSWORD','AWS_STORAGE_BUCKET_NAME'):
                os.environ.pop(key,None)
            before=dict(os.environ)
            with tempfile.TemporaryDirectory() as cache:
                compiled=subject.probe(ROOT,cache)
                self.assertTrue(compiled)  # uncached negative control actually compiled source
                self.assertFalse(any(Path(cache).rglob('*.pyc')))
            self.assertEqual(dict(os.environ),before)

    def test_each_probe_uses_fresh_child_credentials_and_no_jwt_override(self):
        children=[]
        def child(*args,**kwargs):
            children.append(kwargs['env'])
            return SimpleNamespace(returncode=0,stdout=json.dumps({'compiled_source_files':[]})+'\n')
        with patch.dict(os.environ,{'POSTGRES_PASSWORD':'disposable-parent-fixture',
                                    'JWT_SECRET_KEY':'disposable-parent-signing-fixture'}), \
             patch.object(subject.subprocess,'run',side_effect=child):
            before=dict(os.environ)
            subject.probe(ROOT)
            subject.probe(ROOT)
            self.assertEqual(dict(os.environ),before)
        self.assertNotEqual(children[0]['POSTGRES_PASSWORD'],'disposable-parent-fixture')
        self.assertNotEqual(children[0]['POSTGRES_PASSWORD'],children[1]['POSTGRES_PASSWORD'])
        self.assertNotEqual(children[0]['SECRET_KEY'],children[1]['SECRET_KEY'])
        self.assertNotIn('JWT_SECRET_KEY',children[0])
