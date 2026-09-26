import json
from pathlib import Path

import pytest
import requests

FIXTURES_DIR = Path(__file__).parent / 'fixtures'


def pytest_addoption(parser):
    parser.addoption('--live', action='store_true', help='run tests against the real supermarket websites')


def pytest_collection_modifyitems(config, items):
    if config.getoption('--live'):
        return
    skip_live = pytest.mark.skip(reason='needs --live')
    for item in items:
        if 'live' in item.keywords:
            item.add_marker(skip_live)


def load_fixture(name: str) -> bytes:
    """Read a saved response from tests/fixtures (trimmed real pages from each store)."""
    return (FIXTURES_DIR / name).read_bytes()


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, body='', status_code=200):
        self.status_code = status_code
        if isinstance(body, bytes):
            self.content = body
        else:
            self.content = (body if isinstance(body, str) else json.dumps(body)).encode('utf-8')
        self.text = self.content.decode('utf-8')

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f'{self.status_code} Error')


@pytest.fixture
def fake_http(monkeypatch):
    """
    Replace requests.Session.request with canned responses.

    Usage: fake_http({'sklavenitis.gr': FakeResponse(html)}) - each key is matched as a
    substring of the requested URL. A value can also be an exception instance to raise, or a
    function (params, json) -> FakeResponse, e.g. to return a different page per request.
    Unmatched URLs return 404. All calls are recorded in the returned list.
    """
    calls = []

    def install(routes):
        def fake_request(session, method, url, params=None, json=None, **kwargs):
            calls.append({'method': method, 'url': url, 'params': params, 'json': json, 'kwargs': kwargs})
            for fragment, response in routes.items():
                if fragment in url:
                    if callable(response):
                        response = response(params, json)
                    if isinstance(response, Exception):
                        raise response
                    return response
            return FakeResponse('Not found', status_code=404)

        monkeypatch.setattr(requests.Session, 'request', fake_request)
        return calls

    return install
