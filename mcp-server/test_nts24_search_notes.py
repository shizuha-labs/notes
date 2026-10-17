"""NTS-24 (NTS-17 P2-2): unit tests for the expanded notes_search_notes MCP tool.

Covers: the guard (no query + no filter → error, no API call), filter-param
forwarding into the /search/ request (notebook, tag_ids+mode, boolean filters as
"true", date bounds, sort, page_size clamp), snippet rendering (<mark>→**, HTML
strip), search-rank float cast (+ non-numeric skip), and the pagination label.

The notes_search_notes tool calls base.api_request("GET", "/search/", params=...),
so we patch notes_server.base.api_request to capture params / return fixtures.
"""
from unittest.mock import patch

import notes_server
from notes_server import _render_snippet, search_notes


# ── _render_snippet (pure) ───────────────────────────────────────────────────
class TestRenderSnippet:
    def test_mark_becomes_bold_and_other_tags_stripped(self):
        assert _render_snippet('<mark>hit</mark> <i>x</i>y') == '**hit** xy'

    def test_none_and_empty_return_none(self):
        assert _render_snippet(None) is None
        assert _render_snippet('') is None


def _capture(cap):
    """A fake base.api_request that records params and returns a fixture."""
    def _f(method, path, params=None, data=None):
        cap['method'], cap['path'], cap['params'] = method, path, params or {}
        return cap['return']
    return _f


# ── Guard ────────────────────────────────────────────────────────────────────
class TestGuard:
    def test_no_query_no_filter_errors_and_skips_api(self):
        with patch.object(notes_server.base, 'api_request') as m:
            out = search_notes()
        assert out.startswith("Error: at least one of query")
        m.assert_not_called()

    def test_query_only_passes_guard(self):
        cap = {'return': []}
        with patch.object(notes_server.base, 'api_request', _capture(cap)):
            search_notes(query='hello')
        assert cap['path'] == '/search/'
        assert cap['params'].get('q') == 'hello'

    def test_filter_only_passes_guard(self):
        cap = {'return': []}
        with patch.object(notes_server.base, 'api_request', _capture(cap)):
            search_notes(favorite=True)
        assert cap['params'].get('favorite') == 'true'


# ── Filter-param forwarding ──────────────────────────────────────────────────
class TestFilterForwarding:
    def _params(self, **kw):
        cap = {'return': []}
        with patch.object(notes_server.base, 'api_request', _capture(cap)):
            search_notes(**kw)
        return cap['params']

    def test_notebook_sort_and_pagesize_clamp_high(self):
        p = self._params(notebook_id='nb1', sort='updated_desc', limit=999)
        assert p['notebook'] == 'nb1'
        assert p['sort'] == 'updated_desc'
        assert p['page_size'] == 50  # clamped to max 50

    def test_pagesize_floor_low(self):
        assert self._params(query='x', limit=0)['page_size'] == 1

    def test_tag_ids_joined_with_mode(self):
        p = self._params(tag_ids=['t1', 't2'], tag_mode='any')
        assert p['tag_ids'] == 't1,t2'
        assert p['tag_mode'] == 'any'

    def test_boolean_filters_emit_true_strings(self):
        p = self._params(favorite=True, pinned=True, shared_with_me=True)
        assert p['favorite'] == 'true'
        assert p['pinned'] == 'true'
        assert p['shared_with_me'] == 'true'

    def test_false_booleans_not_forwarded(self):
        p = self._params(query='x', favorite=False, pinned=False)
        assert 'favorite' not in p and 'pinned' not in p

    def test_date_bounds_forwarded(self):
        p = self._params(created_after='2026-01-01', updated_before='2026-12-31')
        assert p['created_after'] == '2026-01-01'
        assert p['updated_before'] == '2026-12-31'


# ── Output rendering: snippet / score / pagination ───────────────────────────
class TestOutputRendering:
    def _render(self, result):
        cap = {'return': result}
        with patch.object(notes_server.base, 'api_request', _capture(cap)):
            return search_notes(query='x')

    def test_snippet_and_score_rendered(self):
        out = self._render({'count': 1, 'results': [
            {'title': 'N', 'id': '1', 'snippet': 'a <mark>hit</mark>', 'search_rank': '0.4567'}]})
        assert '**hit**' in out
        assert '0.457' in out  # float cast → 3 decimal places

    def test_non_numeric_score_skipped_no_crash(self):
        out = self._render({'count': 1, 'results': [
            {'title': 'N', 'id': '1', 'score': 'NaNish'}]})
        assert 'Relevance' not in out

    def test_pagination_label(self):
        out = self._render({'count': 40, 'total_pages': 4, 'page': 1,
                            'results': [{'title': 'N', 'id': '1'}]})
        assert 'Page 1/4' in out

    def test_empty_results_message(self):
        assert "No notes found matching 'x'" in self._render({'count': 0, 'results': []})
