"""Explicit tenant membership and response contracts for isolated API tests."""
from unittest.mock import patch


def response_items(response):
    data = response.data
    if isinstance(data, list):
        return data
    # Production pagination must not silently turn its metadata keys into rows.
    assert isinstance(data, dict) and isinstance(data.get('results'), list), 'Expected list or paginated results'
    return data['results']


def configure_membership(testcase, organization_id):
    for module in ('notes.middleware', 'notes.services.access', 'notes.services.search'):
        mocked = patch(module + '.get_user_organization_ids', return_value=[organization_id])
        mocked.start()
        testcase.addCleanup(mocked.stop)
    testcase.client.credentials(HTTP_X_ORGANIZATION_ID=str(organization_id))
