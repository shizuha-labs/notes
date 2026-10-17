#!/usr/bin/env python3
"""Persist a verified frontend image so a later backend Helm upgrade retains it."""
import base64
import json
import os
import re
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def update_tag(content, tag):
    if not re.fullmatch(r'notes-frontend-[0-9a-f]{7,40}', tag):
        raise ValueError('invalid verified frontend tag')
    section = re.search(r'^frontend:\n(?:(?:[ \t].*|)\n)*', content, re.M)
    if not section:
        raise ValueError('frontend values section missing')
    updated, count = re.subn(r'^(    tag: ).*$', lambda match: match[1] + tag, section[0], flags=re.M)
    if count != 1:
        raise ValueError('expected exactly one frontend image tag')
    return content[:section.start()] + updated + content[section.end():]


def is_revision_conflict(error):
    if error.code in (409, 422):
        return True
    # Forgejo's contents API reports a concurrent branch-ref CAS failure as
    # HTTP 500. Retry only that identified conflict, never arbitrary failures.
    if error.code != 500:
        return False
    detail = error.read(8192).decode('utf-8', errors='replace')
    return 'PushRejected' in detail and 'incorrect old value provided' in detail


def main():
    endpoint = os.environ.get('FORGEJO_API_URL', 'http://forgejo-http.origin.svc.cluster.local/api/v1').rstrip('/')
    endpoint += '/repos/shizuha-labs/deploy/contents/k3s/charts/shizuha-notes/values.yaml'
    headers = {'Authorization': 'token ' + os.environ['DEPLOY_PUSH_TOKEN'], 'Content-Type': 'application/json'}
    for attempt in range(5):
        with urlopen(Request(endpoint, headers=headers), timeout=30) as response:
            current = json.load(response)
        content = base64.b64decode(current['content']).decode()
        updated = update_tag(content, os.environ['VERIFIED_FRONTEND_TAG'])
        if updated == content:
            print('Verified frontend tag already persisted')
            return
        body = {'sha': current['sha'], 'content': base64.b64encode(updated.encode()).decode(),
                'message': 'ci(notes): preserve verified frontend image in Helm values [ci skip]'}
        try:
            with urlopen(Request(endpoint, headers=headers, data=json.dumps(body).encode(), method='PUT'), timeout=30):
                pass
            print('Verified frontend tag persisted for future Helm upgrades')
            return
        except HTTPError as error:
            if not is_revision_conflict(error) or attempt == 4:
                raise RuntimeError(f'Chart image persistence failed (HTTP {error.code})') from None
            time.sleep(1)
    raise RuntimeError('Chart image persistence exhausted retries')


if __name__ == '__main__':
    main()
