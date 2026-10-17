"""Prove the built image starts Django without compiling source at runtime."""

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile


PROBE = r'''
import json, os, sys
root = os.getcwd() + "/"
compiled = set()
def audit(event, args):
    if event == "compile" and len(args) > 1:
        filename = args[1]
        if isinstance(filename, str) and filename.startswith(root):
            compiled.add(filename.removeprefix(root))
sys.addaudithook(audit)
import django
django.setup()
print(json.dumps({"compiled_source_files": sorted(compiled)}))
'''


def probe(root, cache_prefix=None):
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "notesmanager.settings",
        "SECRET_KEY": secrets.token_urlsafe(48),
        "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    # No image-build probe needs any reusable signing or database credential.
    env.pop("JWT_SECRET_KEY", None)
    env.pop("PYTHONPYCACHEPREFIX", None)
    if cache_prefix is not None:
        env["PYTHONPYCACHEPREFIX"] = cache_prefix
    result = subprocess.run(
        [sys.executable, "-B", "-c", PROBE], cwd=root, env=env,
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode:
        raise SystemExit("Django bytecode probe failed to start")
    return json.loads(result.stdout.splitlines()[-1])["compiled_source_files"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prove-negative-control", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    compiled = probe(root)
    if compiled:
        raise SystemExit("Runtime source compilation remains: " + ", ".join(compiled))
    if args.prove_negative_control:
        with tempfile.TemporaryDirectory(prefix="notes-bytecode-control-") as cache:
            if not probe(root, cache):
                raise SystemExit("Bytecode detector failed its uncached negative control")
            if any(Path(cache).rglob("*.pyc")):
                raise SystemExit("Startup wrote bytecode despite the runtime read-only policy")
    print("Image bytecode contract passed: real Django startup uses compiled code")


if __name__ == "__main__":
    main()
